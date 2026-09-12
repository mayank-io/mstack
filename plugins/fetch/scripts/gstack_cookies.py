#!/usr/bin/env python3
"""Export the gstack browser's cookies as a Netscape cookie file for yt-dlp/curl.

Why this exists
---------------
`yt-dlp --cookies-from-browser chrome` reads Chrome's DEFAULT profile. gstack runs
its own profile at ~/.gstack/chromium-profile, so the user's logins live somewhere
yt-dlp never looks — and pointing it at the profile path directly still fails,
because the cookie DB is encrypted and locked while the browser is running.

Verified 2026-09-12 against a logged-in Instagram session:

    yt-dlp --cookies-from-browser chrome                       -> login required
    yt-dlp --cookies-from-browser chrome:~/.gstack/chromium-profile -> login required
    browse cookies | this script | yt-dlp --cookies FILE       -> 200, downloads

The daemon hands out the live cookie jar over its own API, which sidesteps both
problems. Any host that needs the user's session (Instagram, and anything else
gated) can use this.

Usage
-----
    python3 gstack_cookies.py OUTFILE [domain-substring ...]

    # everything
    python3 gstack_cookies.py /tmp/cookies.txt
    # just one site
    python3 gstack_cookies.py /tmp/cookies.txt instagram

Prints the number of cookies written to stderr and OUTFILE to stdout.
"""
import json
import os
import subprocess
import sys
import time

BROWSE = os.path.expanduser("~/.claude/skills/gstack/browse/dist/browse")
DEFAULT_TTL = 86400 * 180


def fetch_cookies() -> list:
    """Ask the running gstack daemon for its cookie jar."""
    if not os.path.exists(BROWSE):
        sys.exit(f"gstack browse not found at {BROWSE}")
    out = subprocess.run([BROWSE, "cookies"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"`browse cookies` failed: {out.stderr.strip()[:300]}")
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        sys.exit("`browse cookies` did not return JSON — is the daemon running?")
    return data if isinstance(data, list) else data.get("cookies", [])


def to_netscape(cookies: list, filters: list) -> list:
    """Render cookies as Netscape lines, keeping only hosts matching `filters`."""
    rows = []
    for c in cookies:
        domain = c.get("domain") or ""
        if filters and not any(f in domain for f in filters):
            continue
        # A session cookie has no expiry, and yt-dlp drops rows with expiry 0.
        expires = int(c.get("expires") or c.get("expirationDate") or 0)
        if expires <= 0:
            expires = int(time.time() + DEFAULT_TTL)
        rows.append("\t".join([
            domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            c.get("path", "/"),
            "TRUE" if c.get("secure") else "FALSE",
            str(expires),
            c["name"],
            c.get("value", ""),
        ]))
    return rows


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    outfile, filters = sys.argv[1], sys.argv[2:]
    rows = to_netscape(fetch_cookies(), filters)
    if not rows:
        sys.exit(f"no cookies matched {filters or 'any domain'} — is the browser logged in?")
    with open(outfile, "w") as fh:
        fh.write("# Netscape HTTP Cookie File\n\n" + "\n".join(rows) + "\n")
    os.chmod(outfile, 0o600)          # it holds a live session token
    print(f"wrote {len(rows)} cookies", file=sys.stderr)
    print(outfile)


if __name__ == "__main__":
    main()
