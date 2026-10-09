"""x-account ITERATION layer — thin.

Its whole job: scroll a profile, and for each post open it in a NEW TAB, hand
the open tab to x-post's download unit, close the tab, keep scrolling. It
contains NO extraction, thread, or rendering logic — that is x-post's
(xpost_download). It owns navigation + pacing/budget.

Runs in the user's gstack browser (`_browse.sync_browse_page`), which holds
their X login. It used to launch its own Playwright Chromium on a private
profile at ~/.claude/x-playwright-profile: a second login to keep alive, and a
logged-out run that rendered login walls as short posts. gstack has no element
handles, so a post opens via `newtab <status url>` rather than Cmd+Click; the
profile tab stays open behind it, so X's virtualised timeline keeps its scroll
position between posts.

Run: python3 xaccount_iterate.py <handle> <out_dir> <max_posts>
Progress goes to stderr. Exit 0 done, 2 usage, 3 not logged in to X.
"""
import datetime
import json
import os
import sys
import time

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
from _browse import BrowseError, sync_browse_page  # noqa: E402
from x_session import Budget, Pacer  # noqa: E402
from x_state import ArchiveState  # noqa: E402
import xpost_download  # noqa: E402  x-post's reusable download; NOT reimplemented here

USAGE = "usage: xaccount_iterate.py <handle> <out_dir> <max_posts>"
EXIT_USAGE = 2
EXIT_LOGGED_OUT = 3

CFG = {"scroll_dwell_range": [2.5, 7.0], "read_dwell_range": [8, 35],
       "session_active_range": [12, 17], "session_break_range": [600, 1800],
       "daily_render_budget": 5500, "max_posts_per_hour": 500}

LOGGED_IN_JS = "!!document.querySelector('[data-testid=\"SideNav_AccountSwitcher_Button\"]')"

# self-contained id collector (no dependency on x-post internals)
COLLECT_IDS_JS = ("JSON.stringify(Array.from(document.querySelectorAll('article'))"
  ".map(a=>{const L=Array.from(a.querySelectorAll('a[href*=\"/status/\"]'));"
  "let l=L.find(x=>x.querySelector('time'))||L[0];"
  "const m=l&&l.getAttribute('href').match(/\\/status\\/(\\d+)/);return m?m[1]:null;}).filter(Boolean))")


class NotLoggedIn(RuntimeError):
    pass


def log(m):
    print(m, file=sys.stderr, flush=True)


def parse_args(argv):
    """`(handle, out_dir, max_posts)`, or exit 2 with usage on stderr."""
    if len(argv) != 3:
        print(USAGE, file=sys.stderr)
        raise SystemExit(EXIT_USAGE)
    handle, out, raw = argv
    try:
        maxp = int(raw)
    except ValueError:
        maxp = 0
    if maxp <= 0:
        print(f"max_posts must be a positive integer, got {raw!r}\n{USAGE}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)
    return handle, out, maxp


def _scroll(page, pacer, sleep):
    page.evaluate(f"window.scrollBy(0,{int(pacer.scroll_fraction() * 900)})")
    sleep(pacer.scroll_dwell())


def _download_in_new_tab(page, profile_tab, handle, sid, out, day, pacer, sleep):
    """Open one post in its own tab, download it, and always close the tab and
    return to the profile — whatever the download does."""
    tab = page.new_tab(f"https://x.com/{handle}/status/{sid}")
    try:
        page.wait_for_selector("article", timeout=15000)
        sleep(pacer.read_dwell(600))
        return xpost_download.download_open_post(page, handle, out, day)   # DELEGATE
    except BrowseError as e:
        return {"error": str(e)}
    finally:
        page.close_tab(tab)
        page.switch_tab(profile_tab)


def harvest(page, handle, out, maxp, day, cfg=CFG, sleep=None):
    """Download up to `maxp` notes from `handle`'s timeline; return their filenames.

    Raises NotLoggedIn before opening any tab if the browser is not signed in to X.
    """
    sleep = sleep or time.sleep
    page.goto("https://x.com/home", timeout=45000)
    sleep(3)
    if not page.evaluate(LOGGED_IN_JS):
        raise NotLoggedIn
    pacer = Pacer(7, cfg)
    state = ArchiveState(os.path.join(out, handle))
    budget = Budget(state, day, cfg["daily_render_budget"])
    page.goto(f"https://x.com/{handle}", timeout=45000)
    sleep(pacer.read_dwell(500))
    profile_tab = page.active_tab()

    processed, written, guard = set(), [], 0
    while len(written) < maxp and guard < maxp * 10:
        guard += 1
        if budget.exhausted():
            log(f"daily render budget ({cfg['daily_render_budget']}) exhausted")
            break
        try:
            ids = json.loads(page.evaluate(COLLECT_IDS_JS) or "[]")
        except (BrowseError, ValueError, TypeError):
            ids = []
        nxt = next((i for i in ids if i not in processed), None)
        if nxt is None:
            _scroll(page, pacer, sleep)
            continue
        res = _download_in_new_tab(page, profile_tab, handle, nxt, out, day, pacer, sleep)
        processed.add(nxt)
        if res.get("note"):
            processed.update(res.get("member_ids", []))
            budget.charge(int(res.get("post_count", 1)))
            state.append_post({"status_id": res["status_id"], "date": res["date"],
                               "kind": "thread" if res["is_thread"] else "post",
                               "thread_length": res["post_count"], "status": "extracted",
                               "note": res["note"]})
            written.append(res["fname"])
            log(f"WROTE: [{'thread' if res['is_thread'] else 'post'}, {res['post_count']} posts, "
                f"author={res['author_name']!r}] {res['fname']}")
        else:
            log(f"skip {nxt}: {res.get('error')}")
        _scroll(page, pacer, sleep)
    state.write_manifest({"handle": handle, "post_count": len(written), "enumeration_complete": False})
    return written


def main(argv=None):
    handle, out, maxp = parse_args(sys.argv[1:] if argv is None else argv)
    os.makedirs(out, exist_ok=True)
    day = datetime.date.today().isoformat()
    with sync_browse_page() as page:
        try:
            written = harvest(page, handle, out, maxp, day)
        except NotLoggedIn:
            log("NOT logged in to X in the gstack browser. Log in there "
                "(/open-gstack-browser), then rerun.")
            return EXIT_LOGGED_OUT
    log(f"DONE: {len(written)} notes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
