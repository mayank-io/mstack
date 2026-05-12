// USPTO trademark search via gstack browse.
//
// The tmsearch SPA POSTs to /tmsearch and gets back an Elasticsearch-shaped
// JSON payload. We can't intercept response bodies through the browse CLI
// directly, so we inject a `fetch` override into the page that captures the
// next /tmsearch response body, then read it back via `$B js` after the
// search submits.
//
// We run in HEADED mode for consistency with the WA SoS source (browse's
// daemon mode is process-wide). USPTO doesn't require headed — it just
// requires a real Chrome UA, which browse handles.

import * as B from '../lib/browse.mjs';

export const SOURCE = 'uspto';
export const SCRIPT_VERSION = '0.2.0';
export const LAST_VERIFIED = '2026-05-12';

const SEARCH_URL = 'https://tmsearch.uspto.gov/';
const HEADED = { headed: true };

/**
 * @param {string} query
 * @param {{classes?: number[]|null, timeoutMs?: number}} [opts]
 * @returns {Promise<import('../lib/types.mjs').CheckResult>}
 */
export async function check(query, opts = {}) {
  const classes = opts.classes ?? null;
  const timeoutMs = opts.timeoutMs ?? 45_000;
  const runAt = new Date().toISOString();

  try {
    await B.ensureMode({ headed: true });
    await B.goto(SEARCH_URL, HEADED);
    await B.sleep(1500);

    // Locate the wordmark combobox. The landing page has one labeled "Search trademarks".
    const snap = await B.snapshot(HEADED);
    const searchRef = B.findRef(snap, /\[combobox\]\s+"Search trademarks"/);
    if (!searchRef) {
      return mk({ query, runAt, status: 'error', confidence: 'low', totalCount: 0, records: [],
        note: 'Wordmark combobox not found (selector shifted; see playbook)' });
    }
    const submitRef = B.findRef(snap, /\[button\]\s+"search"/);
    if (!submitRef) {
      return mk({ query, runAt, status: 'error', confidence: 'low', totalCount: 0, records: [],
        note: 'Submit button not found' });
    }

    // Inject capture BEFORE clicking search. We buffer the body via .text(),
    // parse, AND return a fresh Response so the SPA can still consume the body.
    // Doing resp.clone().json() races against the SPA's own body read and
    // aborts ("The user aborted a request") even though clone() is supposed to
    // give an independent stream — only the buffer-and-rewrap pattern works
    // reliably across navigations.
    await B.js(
      `(function(){
         window.__usptoCapture = null;
         if (window.__usptoPatched) return true;
         window.__usptoPatched = true;
         var orig = window.fetch.bind(window);
         window.fetch = function(input, init){
           var url = typeof input === 'string' ? input : (input && input.url) || '';
           if (url.indexOf('/tmsearch') !== -1 && url.indexOf('awswaf') === -1) {
             return orig(input, init).then(function(resp){
               return resp.text().then(function(body){
                 try { window.__usptoCapture = JSON.parse(body); } catch(e) {}
                 return new Response(body, {
                   status: resp.status,
                   statusText: resp.statusText,
                   headers: resp.headers,
                 });
               });
             });
           }
           return orig(input, init);
         };
         return true;
       })()`,
      HEADED,
    );

    await B.fill(searchRef, query, HEADED);
    await B.click(submitRef, HEADED);

    // Poll for capture.
    const captured = await pollCapture(timeoutMs);
    if (!captured) {
      return mk({ query, runAt, status: 'error', confidence: 'low', totalCount: 0, records: [],
        note: 'No /tmsearch API response captured within timeout' });
    }

    const records = extractMarks(captured);
    const filtered = classes
      ? records.filter((r) => r.classes.some((c) => classes.includes(c)))
      : records;

    return mk({ query, runAt,
      variant: classes ? `class-${classes.join('+')}` : 'all-classes',
      status: 'ok',
      confidence: 'high',
      totalCount: filtered.length,
      records: filtered });
  } catch (err) {
    return mk({ query, runAt, status: 'error', confidence: 'low', totalCount: 0, records: [],
      note: `browse error: ${err.message}` });
  }
}

/**
 * Poll `window.__usptoCapture` until populated or timeout.
 * @param {number} timeoutMs
 * @returns {Promise<any|null>}
 */
async function pollCapture(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const raw = await B.js('JSON.stringify(window.__usptoCapture)', HEADED).catch(() => 'null');
    if (raw && raw !== 'null' && raw !== '""' && raw !== 'undefined') {
      try {
        const parsed = JSON.parse(raw);
        if (parsed && parsed.hits) return parsed;
      } catch { /* keep polling */ }
    }
    await B.sleep(400);
  }
  return null;
}

/**
 * Extract Mark[] from the tmsearch API JSON.
 *
 * Payload shape (verified 2026-05):
 *   hits.totalValue                   number
 *   hits.hits[i].id                   serial number (string)
 *   hits.hits[i].source.wordmark      mark text
 *   hits.hits[i].source.alive         boolean
 *   hits.hits[i].source.registrationId  string|null
 *   hits.hits[i].source.cancelDate, abandonDate, registrationDate
 *   hits.hits[i].source.internationalClass  string[] like ["IC 042"]
 *                                           may be prefixed "(CANCELLED) IC 035"
 *   hits.hits[i].source.goodsAndServices    string[]
 *   hits.hits[i].source.ownerName           string[] (most recent first)
 *
 * @param {any} payload
 * @returns {import('../lib/types.mjs').Mark[]}
 */
function extractMarks(payload) {
  const hits = payload?.hits?.hits ?? [];
  return hits.map((hit) => {
    const src = hit.source ?? hit._source ?? {};
    const serial = String(hit.id ?? src.id ?? src.serialNumber ?? '');
    const wordmark = src.wordmark ?? src.markIdentification ?? '';
    const alive = Boolean(src.alive);
    const status = alive ? 'live' : 'dead';
    const detail = deriveDetail(src);
    const classes = parseClasses(src.internationalClass);
    const goodsServices = Array.isArray(src.goodsAndServices)
      ? src.goodsAndServices.join(' | ').slice(0, 500)
      : String(src.goodsAndServices ?? '').slice(0, 500);
    const ownerRaw = Array.isArray(src.ownerName) ? src.ownerName[0] : src.ownerName;
    const owner = parseOwner(ownerRaw ?? '');
    const detailUrl = `https://tsdr.uspto.gov/#caseNumber=${serial}&caseType=SERIAL_NO&searchType=statusSearch`;
    return { serial, wordmark, status, detail, classes, goodsServices, owner, detailUrl };
  });
}

function deriveDetail(src) {
  if (src.alive) return src.registrationId ? 'registered' : 'pending';
  if (src.cancelDate) return 'cancelled';
  if (src.abandonDate) return 'abandoned';
  return 'other';
}

function parseClasses(raw) {
  if (!raw) return [];
  const arr = Array.isArray(raw) ? raw : [raw];
  const out = new Set();
  for (const item of arr) {
    const s = String(item);
    if (/\bcancelled\b/i.test(s)) continue;
    const m = s.match(/\b(\d{3})\b/);
    if (m) out.add(parseInt(m[1], 10));
  }
  return [...out].sort((a, b) => a - b);
}

function parseOwner(raw) {
  if (!raw) return { name: '' };
  const m = String(raw).match(/^(.+?)\s*\(([^;]+);\s*([^)]+)\)\s*$/);
  if (m) return { name: m[1].trim(), type: m[2].trim(), jurisdiction: m[3].trim() };
  return { name: String(raw).trim() };
}

function mk(p) {
  return { source: SOURCE, scriptVersion: SCRIPT_VERSION, scriptLastVerified: LAST_VERIFIED, ...p };
}
