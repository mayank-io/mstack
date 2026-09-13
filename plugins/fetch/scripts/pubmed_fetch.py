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
        "figures": [
            {"label": _label(f.find("label")), "caption": _text(f.find("caption"))}
            for f in root.findall(".//fig")
        ],
        "tables": [
            {"label": _label(t.find("label")), "caption": _text(t.find("caption"))}
            for t in root.findall(".//table-wrap")
        ],
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
            out += ["### Tables", ""] + [
                f"- **{t['label'] or 'Table'}** — {t['caption']}" for t in full["tables"]
            ] + [""]
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
    if not argv:
        print("usage: pubmed_fetch.py <pubmed-url|pmid|pmcid|doi> [output_dir]", file=sys.stderr)
        return 2
    out = Path(argv[1]).expanduser() if len(argv) > 1 else Path.cwd() / f"pubmed-{int(time.time())}"
    try:
        resolved = fetch(argv[0], out)
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
