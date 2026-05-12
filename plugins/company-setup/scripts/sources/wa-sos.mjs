// WA Secretary of State business entity search via gstack browse in HEADED mode.
//
// The CCFS API is gated by Cloudflare Turnstile + AWS WAF. Headless modes are
// silently blocked. With gstack `browse --headed`, Turnstile auto-resolves in
// ~5–10s (the daemon uses a persistent context that retains Cloudflare's
// clearance cookie across runs, and lacks the automation fingerprints
// Playwright's vanilla launch leaves behind).
//
// We read result data from the Angular scope after the search completes
// rather than scraping the rendered DOM — more reliable, JSON-shaped.

import * as B from '../lib/browse.mjs';

export const SOURCE = 'wa-sos';
export const SCRIPT_VERSION = '0.2.0';
export const LAST_VERIFIED = '2026-05-12';

const SEARCH_URL = 'https://ccfs.sos.wa.gov/';
const TURNSTILE_TIMEOUT_MS = 30_000;
const HEADED = { headed: true };

/**
 * @param {string} query
 * @param {{timeoutMs?: number}} [opts]
 * @returns {Promise<import('../lib/types.mjs').CheckResult>}
 */
export async function check(query, opts = {}) {
  const timeoutMs = opts.timeoutMs ?? 90_000;
  const runAt = new Date().toISOString();

  try {
    await B.ensureMode({ headed: true });
    await B.goto(SEARCH_URL, HEADED);
    await B.sleep(2000); // let Angular hydrate

    // Locate the Business Name field. The CCFS landing page has three search
    // forms (Business, Charity, Trademark) — we want the first Business Name.
    const snap = await B.snapshot(HEADED);
    const nameRef = B.findRef(snap, /\[textbox\]\s+"Business Name"/);
    if (!nameRef) {
      return mk({ query, runAt, status: 'error', confidence: 'low', totalCount: 0, records: [],
        note: 'Business Name input not found on landing page (selector may have shifted; see playbook)' });
    }

    // Fill — the Search button starts disabled until Turnstile resolves.
    await B.fill(nameRef, query, HEADED);

    // Wait for Turnstile to populate cf-turnstile-response.
    const tokenReady = await waitFor(
      async () => {
        const v = await B.js(
          "document.querySelector('input[name=\"cf-turnstile-response\"]')?.value?.length || 0",
          HEADED,
        );
        return Number(v) > 0;
      },
      TURNSTILE_TIMEOUT_MS,
    );

    if (!tokenReady) {
      return mk({ query, runAt, status: 'blocked', confidence: 'low', totalCount: 0, records: [],
        blockReason: 'cloudflare-turnstile-unresolved',
        note: 'Turnstile token never populated. Try running again — the persistent profile usually clears it after one successful interaction.' });
    }

    // Re-snapshot to get the now-enabled Search button.
    const snap2 = await B.snapshot(HEADED);
    const submitRef = pickSearchButton(snap2, nameRef);
    if (!submitRef) {
      return mk({ query, runAt, status: 'error', confidence: 'low', totalCount: 0, records: [],
        note: 'Search button not found after Turnstile resolve' });
    }
    await B.click(submitRef, HEADED);

    // Wait for Angular scope to populate. networkidle may not fire — poll the
    // scope until totalCount is defined.
    const settled = await waitFor(
      async () => {
        const raw = await B.js(
          "(function(){var s=angular.element(document.querySelector('[ng-init=\"initBusinessSearch()\"]')).scope(); return typeof s?.totalCount !== 'undefined' && !s?.BusinessListProgressBar;})()",
          HEADED,
        );
        return raw === 'true';
      },
      Math.min(timeoutMs, 30_000),
    );
    if (!settled) await B.sleep(3000); // give it a hail-mary

    const raw = await B.js(
      `(function(){
         var s = angular.element(document.querySelector('[ng-init="initBusinessSearch()"]')).scope();
         if (!s) return JSON.stringify({total: 0, list: []});
         var list = (s.businessList || []).map(function(b){
           return {
             name: b.BusinessName || b.Name || b.EntityName || '',
             ubi:  String(b.UBINumber || b.UBI || b.UBIID || '').replace(/\\s+/g,''),
             type: b.BusinessType || '',
             status: b.BusinessStatus || b.Status || '',
             city: (b.PrincipalOffice && b.PrincipalOffice.PrincipalStreetAddress && b.PrincipalOffice.PrincipalStreetAddress.City) || null
           };
         });
         return JSON.stringify({total: s.totalCount || 0, list: list});
       })()`,
      HEADED,
    );

    /** @type {{total: number, list: any[]}} */
    let parsed;
    try { parsed = JSON.parse(raw); } catch {
      return mk({ query, runAt, status: 'error', confidence: 'low', totalCount: 0, records: [],
        note: `failed to parse Angular scope: ${raw.slice(0, 200)}` });
    }

    const records = parsed.list.map((r) => ({
      ...r,
      detailUrl: r.ubi
        ? `https://ccfs.sos.wa.gov/#/BusinessSearch/BusinessInformation/${r.ubi}`
        : '',
    }));

    return mk({ query, runAt,
      status: 'ok',
      confidence: 'high',
      totalCount: parsed.total,
      records });
  } catch (err) {
    return mk({ query, runAt, status: 'error', confidence: 'low', totalCount: 0, records: [],
      note: `browse error: ${err.message}` });
  }
}

/**
 * Poll fn() every 500ms until it returns truthy or the timeout elapses.
 * @param {() => Promise<boolean>} fn
 * @param {number} timeoutMs
 */
async function waitFor(fn, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if (await fn()) return true;
    } catch {
      // ignore, retry
    }
    await B.sleep(500);
  }
  return false;
}

/**
 * Pick the Search button paired with the given Business Name ref. The ARIA
 * tree lists three identical "Search" buttons (Business, Charity, Trademark);
 * the one we want is the one immediately after the Business Name ref.
 *
 * @param {string} snap
 * @param {string} nameRef e.g. "@e8"
 */
function pickSearchButton(snap, nameRef) {
  const lines = snap.split('\n');
  const idx = lines.findIndex((l) => l.includes(nameRef));
  if (idx === -1) return null;
  for (let i = idx + 1; i < Math.min(idx + 8, lines.length); i++) {
    const m = lines[i].match(/^(\s*@e\d+)\s+\[button\]\s+"Search"/);
    if (m) return m[1].trim();
  }
  return null;
}

function mk(p) {
  return { source: SOURCE, scriptVersion: SCRIPT_VERSION, scriptLastVerified: LAST_VERIFIED, ...p };
}
