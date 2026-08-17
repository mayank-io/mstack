"""x-account ITERATION layer — thin.

Its whole job: scroll a profile, and for each post open it in a NEW TAB
(Cmd+Click, human-style), hand the open tab to x-post's download unit, close
the tab, keep scrolling. It contains NO extraction, thread, or rendering
logic — that is x-post's (xpost_download). It owns navigation + pacing/budget.

Run: python3 xaccount_iterate.py <handle> <out_dir> <max_posts>
Keeps the browser open (idle) at the end.
"""
import sys, os, json, time, datetime

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
from playwright.sync_api import sync_playwright
from x_session import Pacer, Budget
from x_state import ArchiveState
import xpost_download   # <-- x-post's reusable download; NOT reimplemented here

HANDLE, OUT, MAXP = sys.argv[1], sys.argv[2], int(sys.argv[3])
PROFILE = os.path.expanduser("~/.claude/x-playwright-profile")
STOP = os.path.expanduser("~/.claude/x-pilot-stop")
DAY = datetime.date.today().isoformat()
CFG = {"scroll_dwell_range": [2.5, 7.0], "read_dwell_range": [8, 35],
       "session_active_range": [12, 17], "session_break_range": [600, 1800],
       "daily_render_budget": 5500, "max_posts_per_hour": 500}

# self-contained id collector (no dependency on x-post internals)
COLLECT_IDS_JS = ("JSON.stringify(Array.from(document.querySelectorAll('article'))"
  ".map(a=>{const L=Array.from(a.querySelectorAll('a[href*=\"/status/\"]'));"
  "let l=L.find(x=>x.querySelector('time'))||L[0];"
  "const m=l&&l.getAttribute('href').match(/\\/status\\/(\\d+)/);return m?m[1]:null;}).filter(Boolean))")
_ART_ID_JS = ("(a)=>{const L=Array.from(a.querySelectorAll('a[href*=\"/status/\"]'));"
  "let l=L.find(x=>x.querySelector('time'))||L[0];"
  "const m=l&&l.getAttribute('href').match(/\\/status\\/(\\d+)/);return m?m[1]:'';}")

def log(m): print(m, flush=True)

def find_article(page, sid):
    for h in page.query_selector_all("article"):
        try:
            if page.evaluate(_ART_ID_JS, h) == sid:
                return h
        except Exception:
            pass
    return None

def open_in_new_tab(ctx, page, sid):
    art = find_article(page, sid)
    if not art:
        return None
    art.scroll_into_view_if_needed(); time.sleep(0.3)
    target = art.query_selector('[data-testid="tweetText"]') or \
        art.query_selector('a[href*="/status/"]') or art
    with ctx.expect_page() as ev:
        target.click(modifiers=["Meta"])   # Cmd+Click -> new tab
    tab = ev.value
    tab.wait_for_selector("article", timeout=15000)
    return tab

def idle():
    log("BROWSER OPEN (idle). `touch ~/.claude/x-pilot-stop` to close.")
    for _ in range(7200):
        if os.path.exists(STOP): os.remove(STOP); return
        time.sleep(1)

def main():
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(STOP): os.remove(STOP)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE, headless=False,
              viewport={"width": 1300, "height": 900},
              args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("https://x.com/home", timeout=45000); time.sleep(3)
            if not page.evaluate("!!document.querySelector('[data-testid=\"SideNav_AccountSwitcher_Button\"]')"):
                log("NOT logged in."); idle(); return
            pacer = Pacer(7, CFG); state = ArchiveState(os.path.join(OUT, HANDLE))
            budget = Budget(state, DAY, CFG["daily_render_budget"])
            page.goto(f"https://x.com/{HANDLE}", timeout=45000); time.sleep(pacer.read_dwell(500))
            processed, written, guard = set(), [], 0
            while len(written) < MAXP and guard < MAXP * 10:
                guard += 1
                try: ids = json.loads(page.evaluate(COLLECT_IDS_JS) or "[]")
                except Exception: ids = []
                nxt = next((i for i in ids if i not in processed), None)
                if nxt is None:
                    page.evaluate(f"window.scrollBy(0,{int(pacer.scroll_fraction()*900)})")
                    time.sleep(pacer.scroll_dwell()); continue
                tab = open_in_new_tab(ctx, page, nxt)
                if tab is None:
                    processed.add(nxt); continue
                time.sleep(pacer.read_dwell(600))
                res = xpost_download.download_open_post(tab, HANDLE, OUT, DAY)   # DELEGATE
                try: tab.close()
                except Exception: pass
                page.bring_to_front()
                processed.add(nxt)
                if res.get("note"):
                    processed.update(res.get("member_ids", []))
                    budget.charge(res.get("post_count", 1))
                    state.append_post({"status_id": res["status_id"], "date": res["date"],
                                       "kind": "thread" if res["is_thread"] else "post",
                                       "thread_length": res["post_count"], "status": "extracted",
                                       "note": res["note"]})
                    written.append(res["fname"])
                    log(f"WROTE: [{'thread' if res['is_thread'] else 'post'}, {res['post_count']} posts, "
                        f"author={res['author_name']!r}] {res['fname']}")
                else:
                    log(f"skip {nxt}: {res.get('error')}")
                page.evaluate(f"window.scrollBy(0,{int(pacer.scroll_fraction()*900)})")
                time.sleep(pacer.scroll_dwell())
            state.write_manifest({"handle": HANDLE, "post_count": len(written), "enumeration_complete": False})
            log(f"DONE: {len(written)} notes")
            idle()
        finally:
            ctx.close()

main()
