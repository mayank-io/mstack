#!/usr/bin/env python3
"""Fetch a PubMed record — metadata, abstract, and PMC full text when open access.

No browser. PubMed is served by NCBI E-utilities as XML over plain HTTP, so this
is the one fetch skill in the marketplace that never touches gstack. Driving a
browser at pubmed.ncbi.nlm.nih.gov would scrape a rendering of data the API hands
over structured, and would miss the full text entirely.

Emits `OUTPUT_DIR:<path>` as its final stdout line, and nothing on failure.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# NCBI asks for 3 requests/second max without an API key, 10 with one.
# Sleeping the unkeyed interval unconditionally costs a third of a second and
# keeps us inside the limit even when a key is present.
_MIN_INTERVAL = 0.34
_last_request = 0.0


class PubMedError(RuntimeError):
    """Anything that should stop the fetch without printing an OUTPUT_DIR marker."""


# --------------------------------------------------------------- input parsing

def parse_reference(raw: str) -> dict:
    """Resolve a user-supplied reference to {'pmid': ...} or {'pmcid': ...}.

    Accepts a pubmed.ncbi.nlm.nih.gov URL, a PMC URL, a bare PMID, a bare
    PMC id, or a DOI. A DOI cannot be fetched directly — efetch has no DOI
    lookup — so it is returned for the caller to resolve via esearch.
    """
    ref = (raw or "").strip()
    if not ref:
        raise PubMedError("empty reference")

    # PMC first: a PMC URL also contains digits that look like a PMID.
    m = re.search(r"PMC(\d+)", ref, re.I)
    if m:
        return {"pmcid": "PMC" + m.group(1)}

    if re.match(r"^\d{1,9}$", ref):
        return {"pmid": ref}

    if "pubmed.ncbi.nlm.nih.gov" in ref:
        m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", ref)
        if m:
            return {"pmid": m.group(1)}
        q = urllib.parse.parse_qs(urllib.parse.urlparse(ref).query)
        for key in ("term", "pmid"):
            if key in q and re.match(r"^\d+$", q[key][0]):
                return {"pmid": q[key][0]}
        raise PubMedError(f"no PMID in PubMed URL: {ref}")

    if ref.lower().startswith("10.") or "doi.org/" in ref.lower():
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", ref, flags=re.I)
        return {"doi": doi}

    raise PubMedError(f"not a PubMed reference: {ref}")


# ------------------------------------------------------------------- transport

def _get(url: str, params: dict) -> bytes:
    global _last_request
    params = dict(params)
    params.setdefault("tool", "mstack-fetch-pubmed")
    # NCBI asks for a contact address, but sending the user's email to a third
    # party must be their choice — opt in with NCBI_EMAIL, never by default.
    if os.environ.get("NCBI_EMAIL"):
        params["email"] = os.environ["NCBI_EMAIL"]
    if os.environ.get("NCBI_API_KEY"):
        params["api_key"] = os.environ["NCBI_API_KEY"]

    wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)

    full = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(full, headers={"User-Agent": "mstack-fetch-pubmed/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise PubMedError(f"NCBI returned HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise PubMedError(f"cannot reach NCBI: {exc.reason}") from exc
    finally:
        _last_request = time.monotonic()
    return body


def fetch_pubmed_xml(pmid: str) -> bytes:
    return _get(EUTILS, {"db": "pubmed", "id": pmid, "retmode": "xml"})


def fetch_pmc_xml(pmcid: str) -> bytes:
    return _get(EUTILS, {"db": "pmc", "id": pmcid.replace("PMC", ""), "retmode": "xml"})


def resolve_doi(doi: str) -> str:
    """DOI -> PMID via esearch. efetch cannot take a DOI."""
    raw = _get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        {"db": "pubmed", "term": f"{doi}[DOI]", "retmode": "json"},
    )
    ids = json.loads(raw).get("esearchresult", {}).get("idlist", [])
    if not ids:
        raise PubMedError(f"no PubMed record for DOI {doi}")
    return ids[0]


def resolve_pmcid(pmcid: str) -> str:
    """PMC id -> PMID, read from the PMC record's own article-meta."""
    root = ET.fromstring(fetch_pmc_xml(pmcid))
    for el in root.findall(".//article-meta/article-id"):
        if el.get("pub-id-type") == "pmid" and (el.text or "").strip():
            return el.text.strip()
    raise PubMedError(f"no PMID linked from {pmcid}")


# ------------------------------------------------------------------- XML helpers

def _text(el) -> str:
    """Flatten an element including inline markup.

    `el.text` stops at the first child tag. PubMed puts <i> and <b> inside
    <ArticleTitle>, <AbstractText> and <Citation>, so `.text` silently returns
    a prefix of the real string — a truncation that reads as valid content.
    """
    if el is None:
        return ""
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _pub_date(journal) -> str:
    pd = journal.find(".//PubDate")
    if pd is None:
        return ""
    medline = pd.findtext("MedlineDate")
    if medline:
        return medline.strip()
    parts = [pd.findtext(k) for k in ("Year", "Month", "Day")]
    return " ".join(p for p in parts if p)


def parse_pubmed(xml_bytes: bytes) -> dict:
    root = ET.fromstring(xml_bytes)
    article = root.find(".//PubmedArticle")
    if article is None:
        raise PubMedError("no PubmedArticle in response — the PMID may not exist")

    art = article.find(".//Article")
    journal = art.find("Journal")

    # SCOPE THIS. `.//ArticleIdList` also matches the ArticleIdList inside every
    # entry of ReferenceList: on PMID 26041386 that is 103 ids instead of 4, and
    # the first doi you pull out belongs to a cited paper, not this one.
    ids = {}
    idlist = article.find("PubmedData/ArticleIdList")
    if idlist is not None:
        for el in idlist:
            if el.get("IdType") and (el.text or "").strip():
                ids[el.get("IdType")] = el.text.strip()

    authors = []
    for a in art.findall(".//AuthorList/Author"):
        collective = a.findtext("CollectiveName")
        if collective:
            authors.append({"name": collective.strip(), "collective": True})
            continue
        last, fore = a.findtext("LastName"), a.findtext("ForeName")
        if not last:
            continue
        authors.append({
            "last": last.strip(),
            "fore": (fore or "").strip(),
            "name": f"{(fore or '').strip()} {last.strip()}".strip(),
            "affiliations": [_text(x) for x in a.findall(".//AffiliationInfo/Affiliation")],
        })

    abstract = []
    for at in art.findall(".//Abstract/AbstractText"):
        abstract.append({"label": at.get("Label") or "", "text": _text(at)})

    mesh = []
    for mh in article.findall(".//MeshHeadingList/MeshHeading"):
        d = mh.find("DescriptorName")
        if d is None:
            continue
        mesh.append({
            "descriptor": _text(d),
            "major": d.get("MajorTopicYN") == "Y",
            "qualifiers": [
                {"name": _text(q), "major": q.get("MajorTopicYN") == "Y"}
                for q in mh.findall("QualifierName")
            ],
        })

    references = []
    for ref in article.findall(".//ReferenceList/Reference"):
        entry = {"citation": _text(ref.find("Citation"))}
        for el in ref.findall("ArticleIdList/ArticleId"):
            if el.get("IdType") == "pubmed" and (el.text or "").strip():
                entry["pmid"] = el.text.strip()
        references.append(entry)

    return {
        "pmid": article.findtext(".//MedlineCitation/PMID", "").strip(),
        "title": _text(art.find("ArticleTitle")),
        "authors": authors,
        "journal": {
            "title": _text(journal.find("Title")) if journal is not None else "",
            "abbrev": _text(journal.find("ISOAbbreviation")) if journal is not None else "",
            "issn": journal.findtext(".//ISSN", "") if journal is not None else "",
            "volume": journal.findtext(".//Volume", "") if journal is not None else "",
            "issue": journal.findtext(".//Issue", "") if journal is not None else "",
            "pages": art.findtext(".//Pagination/MedlinePgn", ""),
        },
        "pub_date": _pub_date(journal) if journal is not None else "",
        "ids": ids,
        "abstract": abstract,
        "doi": ids.get("doi", ""),
        "pmcid": ids.get("pmc", ""),
        "publication_types": [_text(p) for p in art.findall(".//PublicationTypeList/PublicationType")],
        "keywords": [_text(k) for k in article.findall(".//KeywordList/Keyword")],
        "mesh": mesh,
        "grants": [
            {"id": g.findtext("GrantID", ""), "agency": g.findtext("Agency", "")}
            for g in art.findall(".//GrantList/Grant")
        ],
        "references": references,
        "language": art.findtext(".//Language", ""),
    }


def _bracket_citations(root) -> None:
    """Rewrite <xref ref-type="bibr">13</xref> to [13] in place.

    PMC renders citation markers as superscripts; flattening the tree drops the
    superscript and glues the digits to the preceding word. "presented in
    1983.13" is a real line from PMID 26041386 — the trailing 13 is reference
    13, but it reads as a decimal. Brackets keep the marker unambiguous.
    """
    for xref in root.iter("xref"):
        if xref.get("ref-type") != "bibr":
            continue
        inner = "".join(xref.itertext()).strip()
        if not inner:
            continue
        for child in list(xref):
            xref.remove(child)
        xref.text = f"[{inner}]"


def _label(el) -> str:
    """A figure/table label without its trailing separator — PMC ships 'Table 1:'."""
    return _text(el).rstrip(":.—- ")


FLOAT_TAGS = ("fig", "table-wrap", "supplementary-material")


def _detach_floats(body):
    """Remove figures, tables and supplements from the body tree.

    JATS nests <fig> and <table-wrap> INSIDE a <p>, so leaving them in place
    corrupts the prose twice over: the caption flattens into the surrounding
    paragraph, and `.//p` matches the caption's own <p> as a body paragraph.
    A flattened <table> is worse than duplicated — "Atrial fibrillation48
    961Yes<0.001MarchOctober" is unreadable, and reads as prose rather than as
    a mangled table. Floats are captured separately and rendered properly.
    """
    detached = []
    parents = {child: parent for parent in body.iter() for child in parent}
    for el in list(body.iter()):
        if el.tag in FLOAT_TAGS and el in parents:
            parent = parents[el]
            # The float's tail is real prose — hand it back to the parent.
            if el.tail and el.tail.strip():
                previous = list(parent)
                idx = previous.index(el)
                if idx == 0:
                    parent.text = (parent.text or "") + el.tail
                else:
                    sib = previous[idx - 1]
                    sib.tail = (sib.tail or "") + el.tail
            parent.remove(el)
            detached.append(el)
    return detached


def _span(cell, attr: int) -> int:
    """A colspan/rowspan value, clamped. PMC ships the odd 'colspan="0"'."""
    try:
        return max(1, min(64, int(cell.get(attr) or 1)))
    except ValueError:
        return 1


def _parse_table(table_wrap) -> list[list[str]]:
    """A JATS <table> as a rectangular grid. Empty when there is no grid to read.

    Spans have to be resolved, not ignored. Table 2 of PMID 26041386 heads two
    columns with a colspan'd "Birth Month Risk" over "High"/"Low", and rowspans
    the five columns to its left. Appending cells in document order puts
    "High"/"Low" under "EHR Condition" and "N" — every column label wrong, in a
    table that still looks perfectly well-formed.
    """
    # ALL of them, not the first. PMC splits a table that broke across a page in
    # the original layout into several <table> elements inside one <table-wrap>:
    # Table 2 of PMID 26041386 is 12 rows + 10 rows. find(".//table") returns the
    # first and silently drops the rest, leaving a table that looks complete and
    # is missing seven of its sixteen conditions.
    tables = table_wrap.findall(".//table")
    if not tables:
        return []

    blocks = []
    for table in tables:
        # Spans are resolved per <table>: a rowspan cannot reach across a break.
        grid: dict[tuple[int, int], str] = {}
        taken: set[tuple[int, int]] = set()
        height = 0
        for r, tr in enumerate(table.iter("tr")):
            height = r + 1
            c = 0
            for cell in (e for e in tr if e.tag in ("th", "td")):
                while (r, c) in taken:
                    c += 1
                cols, rows_ = _span(cell, "colspan"), _span(cell, "rowspan")
                grid[(r, c)] = _text(cell)
                for dr in range(rows_):
                    for dc in range(cols):
                        taken.add((r + dr, c + dc))
                c += cols
        if not grid:
            continue
        width = max(c for _, c in taken) + 1
        blocks.append([[grid.get((r, c), "") for c in range(width)] for r in range(height)])

    if not blocks:
        return []
    width = max(len(row) for b in blocks for row in b)
    out = [row + [""] * (width - len(row)) for b in blocks for row in b]
    return [row for row in out if any(row)]


def _render_table(rows: list[list[str]]) -> list[str]:
    """Markdown table. Ragged rows are padded, never truncated."""
    if not rows:
        return []
    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]
    esc = lambda c: c.replace("|", "\\|")
    out = ["| " + " | ".join(esc(c) for c in padded[0]) + " |",
           "|" + "---|" * width]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in padded[1:]]
    return out


def parse_pmc(xml_bytes: bytes) -> dict | None:
    """Structured full text from a PMC record, or None when there is no body.

    A PMID having a PMC id does NOT guarantee retrievable full text: records
    under publisher embargo return a valid document with no <body>.
    """
    root = ET.fromstring(xml_bytes)
    body = root.find(".//body")
    if body is None:
        return None
    _bracket_citations(root)

    # Search from the root, not the body: PMC puts floats in either place — inline
    # in a <p> on some records, hoisted into <floats-group> on others. Collect
    # BEFORE detaching, because detaching mutates the tree.
    figures = [{"label": _label(f.find("label")), "caption": _text(f.find("caption"))}
               for f in root.iter("fig")]
    tables = [{"label": _label(t.find("label")), "caption": _text(t.find("caption")),
               "rows": _parse_table(t)}
              for t in root.iter("table-wrap")]
    _detach_floats(body)

    sections = []
    for sec in body.findall("./sec"):
        sections.append({
            "title": _text(sec.find("title")),
            "paragraphs": [_text(p) for p in sec.findall(".//p") if _text(p)],
        })
    loose = [_text(p) for p in body.findall("./p") if _text(p)]

    return {
        "sections": sections,
        "intro_paragraphs": loose,
        "figures": figures,
        "tables": tables,
        "char_count": len(_text(body)),
    }


# --------------------------------------------------------------------- rendering

def render_markdown(rec: dict, full: dict | None) -> str:
    out = [f"# {rec['title']}", ""]

    names = [a["name"] for a in rec["authors"]]
    if names:
        shown = ", ".join(names) if len(names) <= 12 else ", ".join(names[:12]) + f", … (+{len(names) - 12} more)"
        out += [f"**Authors:** {shown}", ""]

    j = rec["journal"]
    cite = j["abbrev"] or j["title"]
    if j["volume"]:
        cite += f" {j['volume']}"
    if j["issue"]:
        cite += f"({j['issue']})"
    if j["pages"]:
        cite += f":{j['pages']}"
    out += [f"**Source:** {cite} · {rec['pub_date']}", ""]

    links = [f"[PMID {rec['pmid']}](https://pubmed.ncbi.nlm.nih.gov/{rec['pmid']}/)"]
    if rec["doi"]:
        links.append(f"[doi:{rec['doi']}](https://doi.org/{rec['doi']})")
    if rec["pmcid"]:
        links.append(f"[{rec['pmcid']}](https://www.ncbi.nlm.nih.gov/pmc/articles/{rec['pmcid']}/)")
    out += ["**Links:** " + " · ".join(links), "", "---", ""]

    out += ["## Abstract", ""]
    if rec["abstract"]:
        for sec in rec["abstract"]:
            out += ([f"**{sec['label'].title()}.** {sec['text']}"] if sec["label"] else [sec["text"]]) + [""]
    else:
        out += ["*No abstract in the PubMed record.*", ""]

    if full:
        out += ["---", "", "## Full text (PMC)", ""]
        for p in full["intro_paragraphs"]:
            out += [p, ""]
        for sec in full["sections"]:
            if sec["title"]:
                out += [f"### {sec['title']}", ""]
            for p in sec["paragraphs"]:
                out += [p, ""]
        if full["figures"]:
            out += ["### Figures", ""] + [
                f"- **{f['label'] or 'Figure'}** — {f['caption']}" for f in full["figures"]
            ] + [""]
        if full["tables"]:
            out += ["### Tables", ""]
            for t in full["tables"]:
                out += [f"**{t['label'] or 'Table'}** — {t['caption']}", ""]
                if t["rows"]:
                    out += _render_table(t["rows"]) + [""]
                else:
                    out += ["*(table grid not present in the PMC record)*", ""]
    else:
        out += ["---", "", "*Full text not retrievable from PMC — abstract only.*", ""]

    if rec["keywords"]:
        out += ["---", "", "**Keywords:** " + ", ".join(rec["keywords"]), ""]
    if rec["mesh"]:
        terms = [m["descriptor"] + ("*" if m["major"] else "") for m in rec["mesh"]]
        # Semicolons, not commas: descriptors like "Aged, 80 and over" contain commas.
        out += ["**MeSH:** " + "; ".join(terms), ""]

    return "\n".join(out)


# -------------------------------------------------------------------------- CLI

def fetch(reference: str, out_dir: Path) -> Path:
    ref = parse_reference(reference)
    if "doi" in ref:
        print(f"resolving DOI {ref['doi']}", file=sys.stderr)
        pmid = resolve_doi(ref["doi"])
    elif "pmcid" in ref:
        print(f"resolving {ref['pmcid']}", file=sys.stderr)
        pmid = resolve_pmcid(ref["pmcid"])
    else:
        pmid = ref["pmid"]

    # Fetch and parse BEFORE creating the directory, so a bad PMID or a network
    # failure does not leave an empty directory that looks like a partial capture.
    pubmed_xml = fetch_pubmed_xml(pmid)
    rec = parse_pubmed(pubmed_xml)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"pubmed-{pmid}.xml").write_bytes(pubmed_xml)
    print(f"{rec['pmid']}: {rec['title'][:70]}", file=sys.stderr)

    full = None
    if rec["pmcid"]:
        try:
            pmc_xml = fetch_pmc_xml(rec["pmcid"])
            (out_dir / f"pmc-{rec['pmcid']}.xml").write_bytes(pmc_xml)
            full = parse_pmc(pmc_xml)
        except PubMedError as exc:
            print(f"PMC fetch failed ({exc}) — abstract only", file=sys.stderr)
    if full:
        print(f"full text: {full['char_count']} chars, {len(full['sections'])} sections", file=sys.stderr)
    else:
        print("full text: unavailable — abstract only", file=sys.stderr)

    rec["full_text"] = full
    (out_dir / f"{pmid}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    (out_dir / f"{pmid}.md").write_text(render_markdown(rec, full))
    return out_dir


def main(argv: list[str]) -> int:
    usage = "usage: pubmed_fetch.py <pubmed-url|pmid|pmcid|doi> [output_dir]"

    # Accept --output-dir as well as the positional form, and reject any other
    # flag outright. A bare argv scan would otherwise take "--output-dir" itself
    # as the destination and cheerfully create a directory by that name in the
    # caller's cwd — a silent wrong answer, which is the one outcome worth
    # spending code to prevent.
    args, out_flag = [], None
    it = iter(argv)
    for a in it:
        if a in ("-o", "--output-dir"):
            out_flag = next(it, None)
            if out_flag is None:
                print(f"ERROR: {a} needs a directory\n{usage}", file=sys.stderr)
                return 2
        elif a in ("-h", "--help"):
            print(usage)
            return 0
        elif a.startswith("-") and a != "-":
            print(f"ERROR: unknown option {a}\n{usage}", file=sys.stderr)
            return 2
        else:
            args.append(a)

    if not args:
        print(usage, file=sys.stderr)
        return 2
    if len(args) > 2 or (out_flag and len(args) > 1):
        print(f"ERROR: too many arguments\n{usage}", file=sys.stderr)
        return 2

    dest = out_flag or (args[1] if len(args) > 1 else None)
    out = Path(dest).expanduser() if dest else Path.cwd() / f"pubmed-{int(time.time())}"
    try:
        resolved = fetch(args[0], out)
    except PubMedError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ET.ParseError as exc:
        print(f"ERROR: malformed XML from NCBI: {exc}", file=sys.stderr)
        return 1
    print(f"OUTPUT_DIR:{resolved.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
