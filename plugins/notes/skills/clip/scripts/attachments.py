"""Make a note's attachments local, then prove they are there.

A clipping is only an archive if its images live in the vault. Three things have
left them outside it, each producing a note that renders fine online and is
hollow offline:

* a remote image embed, `![](https://…/chart.png)`, which works until the host
  rots or the laptop is on a plane;
* an image inlined as a `data:` URI, which bloats a 4,000-word note to 1.4 MB
  and is not an attachment at all;
* an inline `<svg>…</svg>`, which Obsidian shows as raw markup.

`localize` rewrites all three into files under `<note dir>/attachments/` and
relative embeds. `verify` then checks every embed in the note, whatever wrote
it: the file exists, is not empty, is not an iCloud placeholder, and (for SVG)
parses. With `--obsidian` it also asks the running Obsidian app to resolve each
embed, which is the only check that sees the note the way the reader will.

    python3 attachments.py NOTE.md [--check-only] [--obsidian] [--prefix NAME]

stdout is one JSON object. Exit 0 when every embed is local and present; exit 1
when anything is missing, empty, a placeholder, or failed to download. Embeds
of non-image URLs (a YouTube player) are reported and left alone.
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import xml.dom.minidom

IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp", "svg", "avif", "bmp"}
ATTACHMENT_EXT = IMAGE_EXT | {"pdf", "mp4", "mov", "webm", "mp3", "m4a", "wav",
                              "xls", "xlsx", "csv", "doc", "docx", "ppt", "pptx", "zip"}
SF_DATALESS = 0x40000000   # macOS: the file's contents are in iCloud, not on disk
MIME_EXT = {"png": "png", "jpeg": "jpg", "jpg": "jpg", "gif": "gif", "webp": "webp",
            "svg+xml": "svg", "avif": "avif", "bmp": "bmp"}

_FENCE = re.compile(r"(^```.*?^```[^\n]*$|^~~~.*?^~~~[^\n]*$)", re.S | re.M)
_MD_DATA = re.compile(r"!\[([^\]]*)\]\(data:image/([a-z+]+);base64,([A-Za-z0-9+/=\s]+?)\)")
_IMG_DATA = re.compile(r"<img\b[^>]*?src=\"data:image/([a-z+]+);base64,([A-Za-z0-9+/=\s]+?)\"[^>]*>")
_SVG = re.compile(r"<svg\b.*?</svg>", re.S)
_MD_REMOTE = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")
_MD_EMBED = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_WIKI_EMBED = re.compile(r"!\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")      # a link, not an embed


def sniff(data: bytes):
    """File extension from magic bytes, or None when the bytes are not an image."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    if data[:2] == b"BM":
        return "bmp"
    head = data[:600].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return "svg"
    return None


def fetch(url: str) -> bytes:
    """Download a URL. Returns b"" on any failure; the caller reports it."""
    r = subprocess.run(["curl", "-fsSL", "--max-time", "60", "-A", "Mozilla/5.0", url],
                       capture_output=True, timeout=90, check=False)
    return r.stdout if r.returncode == 0 else b""


def repair_svg(svg: str) -> str:
    """Inline SVG is HTML, not XML: make it a file an XML parser accepts."""
    head, sep, rest = svg.partition(">")
    if "xmlns=" not in head:
        head = head.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    head = re.sub(r"\s(style|class|id)(?=\s|$)(?!=)", r' \1=""', head)   # valueless attributes
    return (head + sep + rest).replace("&nbsp;", "&#160;")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "note"


class Localizer:
    def __init__(self, note_path, prefix=None, fetcher=fetch):
        self.note = os.path.abspath(note_path)
        self.dir = os.path.join(os.path.dirname(self.note), "attachments")
        self.prefix = prefix or slug(os.path.splitext(os.path.basename(self.note))[0])
        self.fetch = fetcher
        self.saved, self.failed, self.skipped = [], [], []

    def _next_name(self, ext):
        os.makedirs(self.dir, exist_ok=True)
        n = 1                               # never reuse a number, whatever its extension
        while any(f.startswith(f"{self.prefix}-{n:02d}.") for f in os.listdir(self.dir)):
            n += 1
        return f"{self.prefix}-{n:02d}.{ext}"

    def _save(self, data, ext):
        name = self._next_name(ext)
        with open(os.path.join(self.dir, name), "wb") as f:
            f.write(data)
        self.saved.append(name)
        return f"attachments/{name}"

    def _data_uri(self, alt, mime, b64, original):
        try:
            data = base64.b64decode(re.sub(r"\s+", "", b64), validate=True)
        except ValueError:
            self.failed.append({"what": "undecodable data: URI", "at": original[:60]})
            return original
        return f"![{alt}]({self._save(data, sniff(data) or MIME_EXT.get(mime, mime))})"

    def _remote(self, m):
        alt, url = m.group(1), m.group(2)
        ext_hint = os.path.splitext(urllib.parse.urlparse(url).path)[1].lstrip(".").lower()
        data = self.fetch(url)
        kind = sniff(data) if data else None
        if kind:
            return f"![{alt}]({self._save(data, kind)})"
        if not data and ext_hint in IMAGE_EXT:
            self.failed.append({"what": "image download failed", "at": url})
        elif not data:
            self.skipped.append({"what": "remote embed, could not fetch, not an image URL", "at": url})
        else:
            self.skipped.append({"what": "remote embed is not an image", "at": url})
        return m.group(0)

    def _svg(self, m):
        return f"![]({self._save(repair_svg(m.group(0)).encode('utf-8'), 'svg')})"

    def rewrite(self, text):
        out = []
        for i, part in enumerate(_FENCE.split(text)):
            if i % 2:                       # fenced code: never touched
                out.append(part)
                continue
            part = _MD_DATA.sub(lambda m: self._data_uri(m.group(1), m.group(2), m.group(3), m.group(0)), part)
            part = _IMG_DATA.sub(lambda m: self._data_uri("", m.group(1), m.group(2), m.group(0)), part)
            part = _SVG.sub(self._svg, part)
            part = _MD_REMOTE.sub(self._remote, part)
            out.append(part)
        return "".join(out)


def vault_root(path):
    d = os.path.dirname(os.path.abspath(path))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, ".obsidian")):
            return d
        d = os.path.dirname(d)
    return None


def embeds(text):
    """(kind, target) for every attachment embed outside fenced code."""
    found = []
    for i, part in enumerate(_FENCE.split(text)):
        if i % 2:
            continue
        for t in _MD_EMBED.findall(part):
            t = t.strip()
            if t.startswith("data:"):
                found.append(("data", t[:40]))
            elif re.match(r"https?://", t):
                found.append(("remote", t))
            else:
                found.append(("path", urllib.parse.unquote(t.split(" ")[0])))
        for t in _WIKI_EMBED.findall(part):
            if os.path.splitext(t)[1].lstrip(".").lower() in ATTACHMENT_EXT:
                found.append(("wiki", t.strip()))
        for t in _MD_LINK.findall(part):
            # a LINK to a local file (a supplementary PDF, a spreadsheet) is an
            # attachment too: it is just as gone when the file is not there
            if re.match(r"[a-z][a-z0-9+.-]*:|#", t, re.I):
                continue
            path = urllib.parse.unquote(t.split("#")[0])
            if os.path.splitext(path)[1].lstrip(".").lower() in ATTACHMENT_EXT:
                found.append(("path", path))
        if _SVG.search(part):
            found.append(("inline-svg", "<svg>"))
    return found


def _resolve_wiki(target, note_path, root):
    direct = os.path.join(os.path.dirname(note_path), target)
    if os.path.exists(direct):
        return direct
    base = os.path.basename(target)
    for r, dirs, files in os.walk(root or os.path.dirname(note_path)):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if base in files:
            return os.path.join(r, base)
    return None


def check_file(path):
    """None when the file is a real local attachment, else the reason it is not."""
    d, b = os.path.split(path)
    if not os.path.exists(path):
        if os.path.exists(os.path.join(d, f".{b}.icloud")):
            return "iCloud placeholder, not downloaded"
        return "missing"
    st = os.stat(path)
    if st.st_size == 0:
        return "empty file"
    if getattr(st, "st_flags", 0) & SF_DATALESS:
        return "iCloud dataless file, not downloaded"
    if path.lower().endswith(".svg"):
        try:
            xml.dom.minidom.parse(path)
        except Exception as e:                       # noqa: BLE001 - any parse error is the finding
            return f"SVG does not parse: {str(e)[:60]}"
    return None


def verify(note_path):
    note_path = os.path.abspath(note_path)
    root = vault_root(note_path)
    text = open(note_path, encoding="utf-8").read()
    ok, problems, remote = [], [], []
    for kind, target in embeds(text):
        if kind == "remote":
            remote.append(target)
        elif kind in ("data", "inline-svg"):
            problems.append({"embed": target, "problem": f"{kind} left in the note, not an attachment"})
        else:
            path = (os.path.normpath(os.path.join(os.path.dirname(note_path), target))
                    if kind == "path" else _resolve_wiki(target, note_path, root))
            if path is None:
                problems.append({"embed": target, "problem": "missing"})
                continue
            why = check_file(path)
            if why:
                problems.append({"embed": target, "problem": why})
            else:
                ok.append(os.path.relpath(path, root or os.path.dirname(note_path)))
    return {"local_ok": ok, "problems": problems, "remote_embeds": remote}


def obsidian_check(note_path, wait=3.0, run=subprocess.run):
    """Ask the running Obsidian app to resolve every embed. Best effort: a
    missing CLI or a closed app is reported as skipped, never as a pass."""
    root = vault_root(note_path)
    if not root:
        return {"status": "skipped", "reason": "note is not inside an Obsidian vault"}
    rel = os.path.relpath(os.path.abspath(note_path), root)
    vault = os.path.basename(root)

    def ev(code):
        return run(["obsidian", f"vault={vault}", "eval", f"code={code}"],
                   capture_output=True, text=True, timeout=60, check=False)
    p = json.dumps(rel)
    try:
        ev(f"app.vault.adapter.reconcileFile({p},{p});1")      # async; `eval` cannot await it
        time.sleep(wait)
        r = ev("(()=>{const f=app.vault.getAbstractFileByPath(" + p + ");if(!f)return JSON.stringify({error:'note not in vault index'});"
               "const e=(app.metadataCache.getFileCache(f)||{}).embeds||[];const bad=[];let n=0;"
               "for(const x of e){let l=x.link;try{l=decodeURIComponent(l)}catch(_){}"
               "if(/^https?:/.test(l))continue;n++;if(!app.metadataCache.getFirstLinkpathDest(l,f.path))bad.push(x.link)}"
               "return JSON.stringify({embeds:n,unresolved:bad})})()")
    except (OSError, subprocess.SubprocessError) as e:
        return {"status": "skipped", "reason": f"obsidian CLI unavailable: {e}"}
    m = re.search(r"\{.*\}", r.stdout or "", re.S)
    if r.returncode != 0 or not m:
        return {"status": "skipped", "reason": (r.stderr or r.stdout or "no reply from Obsidian").strip()[:200]}
    reply = json.loads(m.group(0))
    if reply.get("error"):
        return {"status": "skipped", "reason": reply["error"]}
    return {"status": "ok" if not reply["unresolved"] else "failed", **reply}


def process(note_path, check_only=False, prefix=None, obsidian=False, fetcher=fetch):
    result = {"note": os.path.abspath(note_path), "saved": [], "failed": [], "skipped": []}
    if not check_only:
        text = open(note_path, encoding="utf-8").read()
        loc = Localizer(note_path, prefix=prefix, fetcher=fetcher)
        new = loc.rewrite(text)
        if new != text:
            with open(note_path, "w", encoding="utf-8") as f:
                f.write(new)
        result.update(saved=loc.saved, failed=loc.failed, skipped=loc.skipped)
    result.update(verify(note_path))
    if obsidian:
        result["obsidian"] = obsidian_check(note_path)
    result["ok"] = not result["failed"] and not result["problems"] and \
        result.get("obsidian", {}).get("status") != "failed"
    return result


def main(argv):
    ap = argparse.ArgumentParser(description="Make a note's attachments local, then prove they are there.")
    ap.add_argument("note")
    ap.add_argument("--check-only", action="store_true", help="verify without changing the note")
    ap.add_argument("--obsidian", action="store_true", help="also ask the running Obsidian app")
    ap.add_argument("--prefix", help="filename prefix for saved attachments (default: note name)")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.note):
        print(f"ERROR: no such note: {a.note}", file=sys.stderr)
        return 2
    res = process(a.note, check_only=a.check_only, prefix=a.prefix, obsidian=a.obsidian)
    for p in res["problems"]:
        print(f"PROBLEM: {p['embed']}: {p['problem']}", file=sys.stderr)
    for f in res["failed"]:
        print(f"FAILED: {f['what']}: {f['at']}", file=sys.stderr)
    print(json.dumps(res, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
