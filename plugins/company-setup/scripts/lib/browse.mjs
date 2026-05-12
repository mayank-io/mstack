// Thin wrapper around the gstack `browse` CLI.
//
// Browse is a single-instance headless/headed browser daemon. Its mode
// (headed vs headless) is per-daemon, not per-tab — so callers in the same
// process should agree on a mode (we use headed for everything to keep
// Cloudflare Turnstile happy on WA SoS, and USPTO doesn't care).

import { spawn } from 'node:child_process';
import path from 'node:path';
import os from 'node:os';
import fs from 'node:fs';

const CANDIDATE_PATHS = [
  process.env.BROWSE_BIN,
  path.join(os.homedir(), '.claude/skills/gstack/browse/dist/browse'),
  '/usr/local/bin/browse',
].filter(Boolean);

function resolveBrowseBin() {
  for (const p of CANDIDATE_PATHS) {
    if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
  }
  throw new Error(
    `gstack browse binary not found. Tried:\n  ${CANDIDATE_PATHS.join('\n  ')}\n` +
      `Install gstack from https://github.com/garryslist/gstack or set BROWSE_BIN.`,
  );
}

const BIN = resolveBrowseBin();

/**
 * Run a single browse subcommand. Returns { stdout, stderr, code }.
 * Mode-sticky: pass `headed: true` to use the daemon in headed mode.
 *
 * @param {string[]} argv
 * @param {{headed?: boolean, timeoutMs?: number, input?: string}} [opts]
 */
export function run(argv, opts = {}) {
  const args = opts.headed ? ['--headed', ...argv] : argv;
  return new Promise((resolve, reject) => {
    const child = spawn(BIN, args, { stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    const timer = opts.timeoutMs
      ? setTimeout(() => {
          child.kill('SIGKILL');
          reject(new Error(`browse timed out after ${opts.timeoutMs}ms: ${args.join(' ')}`));
        }, opts.timeoutMs)
      : null;
    child.stdout.on('data', (d) => (stdout += d.toString()));
    child.stderr.on('data', (d) => (stderr += d.toString()));
    if (opts.input) child.stdin.end(opts.input);
    else child.stdin.end();
    child.on('close', (code) => {
      if (timer) clearTimeout(timer);
      resolve({ stdout, stderr, code });
    });
    child.on('error', (err) => {
      if (timer) clearTimeout(timer);
      reject(err);
    });
  });
}

const GSTACK_DIR = path.join(os.homedir(), '.gstack');
const PROFILE_DIR = path.join(GSTACK_DIR, 'chromium-profile');
const PROFILE_LOCK_FILES = ['SingletonLock', 'SingletonCookie', 'SingletonSocket'];

/**
 * Ensure the daemon is running in the requested mode. If it's missing,
 * wrong-moded, or zombied, hard-reset: disconnect, kill any chromium processes
 * pinned to the gstack profile, clear the lockfiles, then let the next browse
 * call lazy-start a fresh daemon.
 *
 * @param {{headed: boolean}} opts
 */
export async function ensureMode(opts) {
  const target = opts.headed ? 'headed' : 'launched';
  // Probe with the target's flag so we don't trigger the "config mismatch" path.
  const probe = await run(['status'], { headed: opts.headed });
  if (process.env.BROWSE_DEBUG) {
    process.stderr.write(
      `[browse] ensureMode probe: code=${probe.code} mode-match=${probe.stdout.match(/Mode:\s*(\S+)/)?.[1] ?? '?'} stderr=${probe.stderr.trim().slice(0, 200)}\n`,
    );
  }
  if (probe.code === 0) {
    const m = probe.stdout.match(/Mode:\s*(\S+)/);
    if (m?.[1] === target) return;
  }
  // Failed or wrong mode. Aggressive cleanup.
  await hardReset();
}

/**
 * Tear down everything pinned to the gstack chromium profile:
 *  1. browse disconnect (in both modes — best-effort)
 *  2. SIGKILL any chromium processes whose argv contains the profile dir
 *     (Playwright sometimes leaks these after a daemon crash)
 *  3. Wait for processes to actually exit
 *  4. Remove Chromium Singleton* lockfiles
 */
async function hardReset() {
  await run(['disconnect'], { headed: false }).catch(() => {});
  await run(['disconnect'], { headed: true }).catch(() => {});

  // pkill is safe — pattern matches only chromium argv that includes our
  // gstack profile path, which other apps won't have.
  await new Promise((resolve) => {
    const child = spawn('pkill', ['-9', '-f', `user-data-dir=${PROFILE_DIR}`]);
    child.on('close', () => resolve());
    child.on('error', () => resolve());
  });

  await new Promise((r) => setTimeout(r, 1500));

  for (const f of PROFILE_LOCK_FILES) {
    try { fs.unlinkSync(path.join(PROFILE_DIR, f)); } catch { /* ignore */ }
  }
}

/** Convenience helpers. All accept { headed } to pin the daemon mode. */
export async function goto(url, opts = {}) {
  const r = await run(['goto', url], opts);
  if (r.code !== 0) throw new Error(`browse goto failed: ${r.stderr || r.stdout}`);
  return r.stdout;
}

export async function snapshot(opts = {}) {
  const r = await run(['snapshot', '-i'], opts);
  return r.stdout;
}

export async function fill(ref, value, opts = {}) {
  const r = await run(['fill', ref, value], opts);
  if (r.code !== 0) throw new Error(`browse fill failed: ${r.stderr || r.stdout}`);
}

export async function click(ref, opts = {}) {
  const r = await run(['click', ref], opts);
  if (r.code !== 0) throw new Error(`browse click failed: ${r.stderr || r.stdout}`);
}

export async function js(expr, opts = {}) {
  const r = await run(['js', expr], opts);
  if (r.code !== 0) throw new Error(`browse js failed: ${r.stderr || r.stdout}`);
  return r.stdout.trim();
}

export async function text(opts = {}) {
  const r = await run(['text'], opts);
  return r.stdout;
}

export async function waitIdle(opts = {}) {
  // networkidle may time out on SPAs with background polling — that's fine.
  await run(['wait', '--networkidle'], opts).catch(() => {});
}

/**
 * Parse the snapshot ARIA tree for a single element by role+name predicate.
 * Returns the @eN ref (e.g. "@e8") or null.
 *
 * @param {string} snap     output of `snapshot -i`
 * @param {RegExp} pattern  matches the rendered line (after ref)
 */
export function findRef(snap, pattern) {
  const lines = snap.split('\n');
  for (const line of lines) {
    const m = line.match(/^(\s*@e\d+)\s+(.+)$/);
    if (m && pattern.test(m[2])) return m[1].trim();
  }
  return null;
}

/** Sleep helper. */
export function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}
