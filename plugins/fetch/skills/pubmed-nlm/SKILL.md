---
name: pubmed-nlm
description: "Fetch a PubMed/NLM biomedical article — metadata, structured abstract, MeSH terms, and PMC full text when open access. Use when the user shares a pubmed.ncbi.nlm.nih.gov URL, a PMID, a PMC id, or a journal DOI and wants to save, clip, read, or summarize the paper."
---

# Fetch PubMed Article

Pull a PubMed record — bibliographic metadata, the structured abstract, MeSH indexing, and the PMC full text when the article is open access — into a directory. **This skill knows nothing about vaults.** It retrieves, and stops. `notes:clip` turns the result into a note.

## No browser — this one is an API

Unlike every other skill in this plugin, **do not open a browser for PubMed.** NCBI publishes the entire corpus through E-utilities as XML over plain HTTP: no login, no cookies, no JavaScript, no rate-limit key for light use. There is no gstack section here because there is nothing for gstack to do.

Driving a browser at `pubmed.ncbi.nlm.nih.gov` would scrape a *rendering* of data the API hands over structured — losing MeSH qualifiers, grant numbers and author affiliations that never appear on the page — and would miss the full text entirely, which lives on a different host under a different id.

## Arguments

- `$ARGUMENTS` should contain: `<url|pmid|pmcid|doi> [output_dir]`

All four reference forms resolve to the same record:

| Input | Resolution |
|---|---|
| `https://pubmed.ncbi.nlm.nih.gov/26041386/` | direct |
| `26041386` | direct |
| `PMC4986668` or a `/pmc/articles/PMC…` URL | reverse-resolved to its PMID via the PMC record |
| `10.1093/jamia/ocv046` or a `doi.org` URL | resolved via `esearch` — **efetch has no DOI lookup** |

## Instructions

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pubmed_fetch.py $ARGUMENTS
```

The script handles everything:

1. Parses the reference and resolves it to a PMID
2. Fetches `efetch.fcgi?db=pubmed&id=<pmid>&retmode=xml`
3. Parses metadata, authors and affiliations, the structured abstract, MeSH headings, keywords, grants and the reference list
4. If the record carries a `pmc` id, fetches `efetch.fcgi?db=pmc&id=<numeric>&retmode=xml` for the full text
5. Writes the raw XML (both documents), a `<pmid>.json` record, and a rendered `<pmid>.md`

Set `NCBI_API_KEY` to raise the rate limit from 3 to 10 requests/second, and `NCBI_EMAIL` to identify yourself to NCBI. Both are optional and neither is sent unless set — **do not add the user's email without being asked.**

## Verification

1. **Check the id count.** The record should carry roughly 2–5 ids (`pubmed`, usually `doi`, often `pmc` and `pii`). Dozens means the reference list leaked into them — see Notes.
2. **Check the abstract reassembles.** A structured abstract's sections should read as continuous prose. A section ending mid-clause means inline markup truncated it.
3. **Say whether full text was retrieved.** The script prints `full text: <n> chars` or `full text: unavailable — abstract only` to stderr. Abstract-only is a normal outcome, not a failure — but report which one happened rather than letting the reader assume.

## Notes — the traps, each measured on a real record

- **Scope the article ids.** `.//ArticleIdList/ArticleId` also matches the id list inside every `<Reference>`: on PMID 26041386 that is **103 ids instead of 4**, and the first `doi` among them belongs to a *cited* paper. The record parses cleanly and points at the wrong article. The anchored path is `PubmedData/ArticleIdList`.
- **Never use `elem.text` on PubMed XML.** `.text` is the text *before the first child element*, not the element's text. `<ArticleTitle>Risk of <i>P. falciparum</i> infection</ArticleTitle>` yields `"Risk of "` — a truncation with no error and no marker. Use `''.join(elem.itertext())` throughout.
- **MeSH indexing is not guaranteed.** PMID 29036387 has no `MeshHeadingList` at all — newer and unindexed records simply lack one. Treat its absence as normal, never as a failed parse.

- **Figures and tables are nested *inside* the prose, not beside it.** JATS puts `<fig>` and `<table-wrap>` within a `<p>`, so a naive flatten does two things at once: the caption is glued into the surrounding sentence, and `.//p` matches the caption's own `<p>` a second time as a body paragraph. Worse, a flattened `<table>` becomes `Atrial fibrillation48 961Yes<0.001MarchOctober` — corrupted data wearing the shape of prose. The script detaches floats before reading the body (handing the float's tail text back to its parent) and renders tables as real markdown grids. On PMID 26041386 this is the difference between a 35,603-character body and a 29,323-character one; the missing 6,280 characters were duplicated captions and mangled table cells.
- **Resolve `colspan` and `rowspan` before emitting rows.** Table 2 of PMID 26041386 heads two columns with a colspan'd *Birth Month Risk* over *High*/*Low*, and rowspans the five columns to its left. Appending cells in document order puts *High*/*Low* under *EHR Condition* and *N* — every column label wrong, in a table that still renders perfectly well-formed.

Three smaller ones, all handled by the script:

- **A `pmc` id does not guarantee full text.** Embargoed records return a valid document with no `<body>`. The script reports abstract-only rather than an empty section.
- **A cell can be legitimately empty.** Table 2's *Seasonal Pattern* column holds sparkline graphics, not text, so it comes through blank. That is the honest rendering — the column exists and its content is an image the record does not hand over.
- **PMC citation superscripts flatten into the prose.** `presented in 1983<sup><xref>13</xref></sup>` becomes `presented in 1983.13`, which reads as a decimal. The script brackets them: `1983.[13]`.

- **Figure captions are captured; figure images are not.** The PMC XML names each graphic (`ocv046f1p.jpg`) but the file is not served from a predictable URL — `/pmc/articles/<id>/bin/<name>`, the `pmc.ncbi.nlm.nih.gov` equivalent, and the legacy `utils/oa/oa.fcgi` service all returned 404 for PMID 26041386 (checked 2026-09-14). Articles inside the PMC **Open Access subset** ship their images in a downloadable package; most publisher-deposited articles, including these JAMIA ones, do not. Report figures as caption-only rather than implying the images were fetched.

Abstract section labels differ between records — `METHODS` vs `MATERIAL AND METHODS`, `CONCLUSIONS` vs `CONCLUSION`. Render whatever labels arrive; do not normalise them to a fixed set.

## Output

The script prints progress to stderr and the directory as the **final stdout line**:

```
OUTPUT_DIR:/absolute/path/to/output
```

The marker must be last, and **nothing is printed on failure** — callers chain on it and must never reconstruct the path. A bad PMID, an unrecognised reference, or an unreachable NCBI exits non-zero with an `ERROR:` line on stderr and creates no directory.

## Example Usage

```bash
# By URL, into a temp directory
/fetch:pubmed-nlm https://pubmed.ncbi.nlm.nih.gov/26041386/

# By bare PMID, into a named directory
/fetch:pubmed-nlm 26041386 ./papers/birth-month

# By DOI or PMC id
/fetch:pubmed-nlm 10.1093/jamia/ocx105 ./papers/exposures
/fetch:pubmed-nlm PMC4986668 ./papers/birth-month
```
