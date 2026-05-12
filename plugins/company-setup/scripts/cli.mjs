#!/usr/bin/env node
// CLI orchestrator. Runs each requested source in parallel, aggregates,
// emits a markdown report on stdout (or JSON with --json). Progress notes
// go to stderr.

import { check as checkUspto } from './sources/uspto.mjs';
import { check as checkWaSos } from './sources/wa-sos.mjs';
import { check as checkDomain } from './sources/domain.mjs';
import { aggregate } from './lib/verdict.mjs';

function parseArgs(argv) {
  const args = { positional: [], systems: ['uspto', 'wa-sos', 'domain'], classes: null, json: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--systems') {
      args.systems = argv[++i].split(',').map((s) => s.trim());
    } else if (a === '--class') {
      args.classes = argv[++i].split(',').map((c) => parseInt(c.trim(), 10)).filter(Number.isFinite);
    } else if (a === '--json') {
      args.json = true;
    } else if (a === '--refresh') {
      args.refresh = true; // reserved for cache layer
    } else if (a === '--self-test') {
      args.selfTest = true;
    } else if (a === '--help' || a === '-h') {
      args.help = true;
    } else if (a.startsWith('--')) {
      console.error(`unknown flag: ${a}`);
      process.exit(2);
    } else {
      args.positional.push(a);
    }
  }
  return args;
}

function usage() {
  console.error(`
Usage: node cli.mjs <candidate-name> [flags]

  --systems <csv>   uspto,wa-sos,domain (default: all)
  --class <csv>     USPTO class filter (e.g. 35,42)
  --json            emit JSON instead of markdown
  --refresh         bypass cache (reserved)
  --self-test       run health checks against known queries

Examples:
  node cli.mjs solidus
  node cli.mjs "solidus tech advisory" --systems uspto,wa-sos
  node cli.mjs sondage --class 35,42
`.trim());
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.help) { usage(); process.exit(0); }
  if (args.selfTest) {
    await selfTest();
    return;
  }

  if (args.positional.length === 0) {
    console.error('error: candidate name required');
    usage();
    process.exit(2);
  }

  const candidate = args.positional.join(' ');
  console.error(`[check-name] candidate: "${candidate}"`);
  console.error(`[check-name] systems: ${args.systems.join(',')}`);
  if (args.classes) console.error(`[check-name] uspto classes: ${args.classes.join(',')}`);

  // Domain check has no browser dep — run it in parallel.
  // wa-sos and uspto both drive the gstack browse daemon (single instance,
  // single active tab), so they MUST run sequentially.
  const domainPromise = args.systems.includes('domain')
    ? runSource('domain', () => checkDomain(candidate))
    : null;

  /** @type {any[]} */
  const browseResults = [];
  if (args.systems.includes('wa-sos')) {
    browseResults.push(await runSource('wa-sos', () => checkWaSos(candidate)));
  }
  if (args.systems.includes('uspto')) {
    browseResults.push(
      await runSource('uspto', () => checkUspto(candidate, { classes: args.classes })),
    );
  }

  const results = [...browseResults];
  if (domainPromise) results.push(await domainPromise);
  const { overall, risks, reportMd } = aggregate(results, {
    candidate,
    targetClasses: args.classes ?? undefined,
  });

  if (args.json) {
    process.stdout.write(JSON.stringify({ candidate, overall, risks, results }, null, 2) + '\n');
  } else {
    process.stdout.write(reportMd + '\n');
  }
}

async function runSource(name, fn) {
  const t0 = Date.now();
  console.error(`[${name}] starting...`);
  try {
    const r = await fn();
    const dt = ((Date.now() - t0) / 1000).toFixed(1);
    console.error(`[${name}] done in ${dt}s — status=${r.status} count=${r.totalCount}`);
    return r;
  } catch (err) {
    console.error(`[${name}] FAILED — ${err.message}`);
    return {
      source: name,
      query: '',
      runAt: new Date().toISOString(),
      status: 'error',
      confidence: 'low',
      totalCount: 0,
      records: [],
      scriptVersion: 'unknown',
      scriptLastVerified: 'unknown',
      note: err.message,
    };
  }
}

async function selfTest() {
  console.error('[self-test] running canary queries...');
  const usptoCanary = await checkUspto('MICROSOFT');
  console.error(`[self-test] uspto MICROSOFT — status=${usptoCanary.status} count=${usptoCanary.totalCount}`);
  const waCanary = await checkWaSos('MICROSOFT');
  console.error(`[self-test] wa-sos MICROSOFT — status=${waCanary.status} count=${waCanary.totalCount}`);
  const domCanary = await checkDomain('microsoft');
  console.error(`[self-test] domain microsoft — status=${domCanary.status} registered=${domCanary.records.filter(r => r.registered).length}/${domCanary.records.length}`);

  const passed =
    usptoCanary.status === 'ok' && usptoCanary.totalCount >= 50 &&
    waCanary.status === 'ok' && waCanary.totalCount >= 1 &&
    domCanary.records.some((r) => r.domain === 'microsoft.com' && r.registered);

  if (passed) {
    console.error('[self-test] PASS');
    process.exit(0);
  } else {
    console.error('[self-test] FAIL — selectors or APIs may have shifted; consult playbooks/');
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('fatal:', err);
  process.exit(1);
});
