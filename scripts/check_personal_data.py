#!/usr/bin/env python3
"""Find personal data in files that this public repository is about to ship.

Three kinds of rule:

  private terms  Words read from a file OUTSIDE the repository (default
                 ~/.mstack/private-terms.txt), because the list is itself
                 personal: names, a vault name, private project names, internal
                 hostnames. One term per line, `#` comments. Matched
                 case-insensitively on word boundaries; prefix a term with
                 `cs:` to match it case-sensitively. `dirs:<directory>` makes
                 every subdirectory name a term, so a new personal project is
                 covered as soon as its directory exists; `not:<term>` drops one.
  patterns       Shapes that are personal whatever the words are: a home
                 directory path, an email address, a phone number, a numeric id
                 in a URL, an iCloud vault path.
  paths          Files that are per-user config and do not belong in a plugin.

A line carrying `personal-data-ok` is skipped. The allow file (default
scripts/personal-data-allow.txt) holds `<path glob><TAB><regex>` entries: in a
file the glob matches, text the regex matches is blanked before the line is
scanned, so an entry excuses exactly what it names and nothing else on the line.
The allow file itself is not scanned: it states the accepted exposures.

Usage:
    check_personal_data.py --staged            # the index (pre-commit)
    check_personal_data.py --all               # every tracked file
    check_personal_data.py FILE [FILE ...]     # named files
    options: --terms PATH | --no-private-terms, --allow PATH

stdout: one finding per line, `path:line: rule: matched text`.
Exit 0 clean, 1 findings, 2 cannot run (no terms file, not a git repository).
A missing terms file is exit 2, never a pass: a scan that could not look for
the private terms has not found the tree clean.
"""

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

OK_MARKER = "personal-data-ok"
DEFAULT_TERMS = Path(os.path.expanduser("~/.mstack/private-terms.txt"))
DEFAULT_ALLOW = Path(__file__).resolve().parent / "personal-data-allow.txt"

PLACEHOLDER_USERS = {"alex", "example", "jane", "john", "me", "name", "user", "username", "you"}
PLACEHOLDER_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "anthropic.com", "users.noreply.github.com"}
NON_PERSON_EMAIL_LOCALS = {"git", "noreply"}

HOME_PATH = re.compile(r"/Users/([A-Za-z0-9._-]+)/|/home/([A-Za-z0-9._-]+)/")
EMAIL = re.compile(r"\b([A-Za-z0-9._%+-]+)@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})\b")
PHONE = re.compile(r"(?<![\w.-])\(?\d{3}\)?[-. ]\d{3}[-.]\d{4}(?![\w-])")
URL_ID = re.compile(r"[?&][A-Za-z_]*id=\d{5,}")
ICLOUD_VAULT = re.compile(r"iCloud~md[~]obsidian")

USER_CONFIG_PATHS = (
    ("plugins/*/templates/channels/*", None),
    ("plugins/*/config-defaults/channels/*", "example.md"),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    text: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.text}"


def load_terms(path: Path) -> list[re.Pattern]:
    """Compile the private terms file. Raises OSError when it cannot be read.

    Lines: a term; `cs:<term>` for a case-sensitive term; `dirs:<directory>` to
    make the name of every immediate subdirectory a term (so a new project
    directory is covered the day it is created); `not:<term>` to drop a term
    that `dirs:` produced but is not private.
    """
    terms: dict[str, int] = {}
    excluded: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("not:"):
            excluded.add(line[4:].strip().lower())
        elif line.startswith("dirs:"):
            directory = Path(os.path.expanduser(line[5:].strip()))
            for child in sorted(directory.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    terms.setdefault(child.name, re.IGNORECASE)
        elif line.startswith("cs:"):
            terms[line[3:].strip()] = 0
        else:
            terms[line] = re.IGNORECASE
    return [
        re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", flags)
        for term, flags in terms.items()
        if term.lower() not in excluded
    ]


def load_allow(path: Path) -> list[tuple[str, re.Pattern]]:
    """Read `<glob><TAB><regex>` entries. A missing allow file allows nothing."""
    if not path.is_file():
        return []
    entries = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.startswith("#"):
            continue
        glob, sep, regex = raw.partition("\t")
        if not sep or not regex:
            raise ValueError(f"{path}:{number}: expected '<path glob><TAB><regex>'")
        entries.append((glob.strip(), re.compile(regex)))
    return entries


def mask_allowed(path: str, line: str, allow: list[tuple[str, re.Pattern]]) -> str:
    """The line with every allowed match blanked, or empty when the line is marked ok."""
    if OK_MARKER in line:
        return ""
    for glob, regex in allow:
        if fnmatch.fnmatch(path, glob):
            line = regex.sub(lambda m: " " * len(m.group(0)), line)
    return line


def scan_line(line: str, terms: list[re.Pattern]) -> list[tuple[str, str]]:
    """Every (rule, matched text) on one line."""
    hits = []
    for term in terms:
        for m in term.finditer(line):
            hits.append(("private-term", m.group(0)))
    for m in HOME_PATH.finditer(line):
        if (m.group(1) or m.group(2)).lower() not in PLACEHOLDER_USERS:
            hits.append(("home-path", m.group(0)))
    for m in EMAIL.finditer(line):
        if m.group(2).lower() not in PLACEHOLDER_EMAIL_DOMAINS and m.group(1).lower() not in NON_PERSON_EMAIL_LOCALS:
            hits.append(("email", m.group(0)))
    for m in PHONE.finditer(line):
        hits.append(("phone", m.group(0)))
    for m in URL_ID.finditer(line):
        hits.append(("url-id", m.group(0)))
    for m in ICLOUD_VAULT.finditer(line):
        hits.append(("icloud-vault", m.group(0)))
    return hits


def scan_path_rules(path: str) -> list[Finding]:
    """Per-user config that must live in ~/.mstack, not in a plugin."""
    for glob, permitted in USER_CONFIG_PATHS:
        if fnmatch.fnmatch(path, glob) and os.path.basename(path) != permitted:
            return [Finding(path, 0, "user-config-path", "per-user config belongs in ~/.mstack/<plugin>/")]
    return []


def scan_text(path: str, text: str, terms: list[re.Pattern], allow: list[tuple[str, re.Pattern]]) -> list[Finding]:
    findings = scan_path_rules(path)
    for number, line in enumerate(text.splitlines(), 1):
        for rule, matched in scan_line(mask_allowed(path, line, allow), terms):
            findings.append(Finding(path, number, rule, matched))
    return findings


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def decode(data: bytes) -> str | None:
    """Text of a file, or None when it is binary."""
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def collect_staged() -> list[tuple[str, bytes]]:
    names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0")
    return [(n.decode(), git("show", f":{n.decode()}")) for n in names if n]


def collect_all(root: Path) -> list[tuple[str, bytes]]:
    names = git("-C", str(root), "ls-files", "-z").split(b"\0")
    return [(n.decode(), (root / n.decode()).read_bytes()) for n in names if n and (root / n.decode()).is_file()]


def collect_named(root: Path, files: list[str]) -> list[tuple[str, bytes]]:
    out = []
    for name in files:
        path = Path(name).resolve()
        out.append((str(path.relative_to(root)) if path.is_relative_to(root) else name, path.read_bytes()))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="scan the index")
    mode.add_argument("--all", action="store_true", help="scan every tracked file")
    ap.add_argument("files", nargs="*", help="files to scan when neither --staged nor --all is given")
    ap.add_argument("--terms", type=Path, default=DEFAULT_TERMS, help="private terms file (default ~/.mstack/private-terms.txt)")
    ap.add_argument("--no-private-terms", action="store_true",
                    help="run the pattern and path rules only (CI, where the terms file does not exist)")
    ap.add_argument("--allow", type=Path, default=DEFAULT_ALLOW, help="allow file (default scripts/personal-data-allow.txt)")
    args = ap.parse_args(argv)

    if not (args.staged or args.all or args.files):
        ap.error("give --staged, --all, or one or more files")

    terms: list[re.Pattern] = []
    if not args.no_private_terms:
        try:
            terms = load_terms(args.terms)
        except OSError:
            print(f"check-personal-data: cannot read {args.terms}; nothing was checked. "
                  "Create it (one private term per line) or pass --no-private-terms.", file=sys.stderr)
            return 2
        if not terms:
            print(f"check-personal-data: {args.terms} lists no terms; nothing was checked.", file=sys.stderr)
            return 2

    try:
        allow = load_allow(args.allow)
        root = Path(git("rev-parse", "--show-toplevel").decode().strip())
        if args.staged:
            files = collect_staged()
        elif args.all:
            files = collect_all(root)
        else:
            files = collect_named(root, args.files)
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(f"check-personal-data: {exc}", file=sys.stderr)
        return 2

    # The allow file states the accepted exposures, so it necessarily contains them.
    allow_file = args.allow.resolve()
    findings: list[Finding] = []
    for path, data in files:
        if (root / path).resolve() == allow_file:
            continue
        text = decode(data)
        findings.extend(scan_path_rules(path) if text is None else scan_text(path, text, terms, allow))

    for finding in findings:
        print(finding.render())
    if findings:
        print(f"check-personal-data: {len(findings)} finding(s) in {len({f.path for f in findings})} file(s). "
              f"Remove them, or mark a line `{OK_MARKER}: <reason>`, or add an entry to {args.allow.name}.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
