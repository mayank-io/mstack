// Domain availability via RDAP. No browser required.
// RDAP is the modern replacement for WHOIS — returns JSON, well-defined schema,
// supported by all major TLD registries.

export const SOURCE = 'domain';
export const SCRIPT_VERSION = '0.1.0';
export const LAST_VERIFIED = '2026-05-12';

const DEFAULT_TLDS = ['com', 'io', 'co', 'ai'];

const RDAP_BOOTSTRAP = {
  com: 'https://rdap.verisign.com/com/v1/domain/',
  net: 'https://rdap.verisign.com/net/v1/domain/',
  io:  'https://rdap.identitydigital.services/rdap/domain/',
  co:  'https://rdap.nic.co/domain/',
  ai:  'https://rdap.nic.ai/domain/',
  dev: 'https://rdap.nic.google/domain/',
  app: 'https://rdap.nic.google/domain/',
  xyz: 'https://rdap.centralnic.com/xyz/domain/',
};

/**
 * @param {string} query
 * @param {{tlds?: string[], timeoutMs?: number}} [opts]
 * @returns {Promise<import('../lib/types.mjs').CheckResult>}
 */
export async function check(query, opts = {}) {
  const tlds = opts.tlds ?? DEFAULT_TLDS;
  const timeoutMs = opts.timeoutMs ?? 10_000;
  const runAt = new Date().toISOString();

  const slug = sanitize(query);
  const results = await Promise.all(
    tlds.map((tld) => checkOne(slug, tld, timeoutMs)),
  );

  const ok = results.filter((r) => r != null);
  return {
    source: SOURCE,
    query,
    runAt,
    status: ok.length > 0 ? 'ok' : 'error',
    confidence: 'high',
    totalCount: ok.length,
    records: ok,
    scriptVersion: SCRIPT_VERSION,
    scriptLastVerified: LAST_VERIFIED,
  };
}

async function checkOne(slug, tld, timeoutMs) {
  const base = RDAP_BOOTSTRAP[tld];
  if (!base) {
    return {
      domain: `${slug}.${tld}`,
      registered: false,
      registrar: null,
      expiresAt: null,
      lastChangedAt: null,
    };
  }
  const url = `${base}${slug}.${tld}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/rdap+json' } });
    clearTimeout(timer);
    if (resp.status === 404) {
      return {
        domain: `${slug}.${tld}`,
        registered: false,
        registrar: null,
        expiresAt: null,
        lastChangedAt: null,
      };
    }
    if (!resp.ok) {
      return {
        domain: `${slug}.${tld}`,
        registered: false,
        registrar: null,
        expiresAt: null,
        lastChangedAt: null,
        note: `RDAP HTTP ${resp.status}`,
      };
    }
    const body = await resp.json();
    return {
      domain: `${slug}.${tld}`,
      registered: true,
      registrar: extractRegistrar(body),
      expiresAt: extractEvent(body, 'expiration'),
      lastChangedAt: extractEvent(body, 'last changed'),
    };
  } catch (err) {
    return {
      domain: `${slug}.${tld}`,
      registered: false,
      registrar: null,
      expiresAt: null,
      lastChangedAt: null,
      note: `rdap-error: ${err.message}`,
    };
  } finally {
    clearTimeout(timer);
  }
}

function extractRegistrar(body) {
  const entities = body?.entities ?? [];
  const registrar = entities.find((e) => (e.roles ?? []).includes('registrar'));
  if (!registrar) return null;
  const vcard = registrar.vcardArray?.[1] ?? [];
  const fn = vcard.find((e) => Array.isArray(e) && e[0] === 'fn');
  return fn?.[3] ?? registrar.handle ?? null;
}

function extractEvent(body, action) {
  const events = body?.events ?? [];
  const evt = events.find((e) => String(e.eventAction).toLowerCase().includes(action));
  return evt?.eventDate ?? null;
}

function sanitize(q) {
  return q.toLowerCase().replace(/[^a-z0-9-]/g, '');
}
