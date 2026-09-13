"""Tests for the PubMed fetch unit's parsing seams.

These do NOT hit the network. They pin the places where this parser can go
silently wrong — each one yields a record that *looks* complete and is not:

1. `.//ArticleIdList/ArticleId` also matches the id list inside every
   <Reference>. On PMID 26041386 that is 103 ids instead of 4, and the first
   doi belongs to a cited paper. The record parses, and points elsewhere.
2. `elem.text` stops at the first child tag. PubMed puts <i> and <b> inside
   abstracts and titles, so `.text` returns a prefix — a truncation with no
   error and no marker.
3. MeSH indexing is not guaranteed. PMID 29036387 has no MeshHeadingList at
   all; assuming one raises on a perfectly valid record.
4. PMC flattens citation superscripts into the prose. "presented in 1983.13"
   is a real line — the 13 is reference 13, but it reads as a decimal.
5. A PMC id does not guarantee full text: embargoed records return a valid
   document with no <body>.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pubmed_fetch  # noqa: E402
from pubmed_fetch import PubMedError  # noqa: E402


# The reference's ArticleIdList carries a DIFFERENT doi to the article's own.
# That is the whole point: an unscoped search cannot tell them apart.
ARTICLE_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet><PubmedArticle>
  <MedlineCitation>
    <PMID>26041386</PMID>
    <Article>
      <Journal>
        <ISSN>1067-5027</ISSN>
        <Title>Journal of the American Medical Informatics Association</Title>
        <ISOAbbreviation>J Am Med Inform Assoc</ISOAbbreviation>
        <JournalIssue><Volume>22</Volume><Issue>5</Issue>
          <PubDate><Year>2015</Year><Month>Sep</Month></PubDate></JournalIssue>
      </Journal>
      <ArticleTitle>Risk of <i>P. falciparum</i> infection by birth month.</ArticleTitle>
      <Pagination><MedlinePgn>1042-53</MedlinePgn></Pagination>
      <Abstract>
        <AbstractText Label="OBJECTIVE">Explore <i>seasonal</i> effects.</AbstractText>
        <AbstractText Label="MATERIAL AND METHODS">We used logistic regression.</AbstractText>
      </Abstract>
      <AuthorList>
        <Author><LastName>Boland</LastName><ForeName>Mary Regina</ForeName>
          <AffiliationInfo><Affiliation>Columbia University</Affiliation></AffiliationInfo></Author>
        <Author><CollectiveName>The SeaWAS Group</CollectiveName></Author>
      </AuthorList>
      <Language>eng</Language>
      <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
      <GrantList><Grant><GrantID>R01 LM006910</GrantID><Agency>NLM NIH HHS</Agency></Grant></GrantList>
    </Article>
    <MeshHeadingList>
      <MeshHeading><DescriptorName MajorTopicYN="N">Adolescent</DescriptorName></MeshHeading>
      <MeshHeading><DescriptorName MajorTopicYN="Y">Seasons</DescriptorName>
        <QualifierName MajorTopicYN="N">statistics &amp; numerical data</QualifierName></MeshHeading>
    </MeshHeadingList>
    <KeywordList><Keyword>seasons</Keyword><Keyword>pregnancy</Keyword></KeywordList>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">26041386</ArticleId>
      <ArticleId IdType="pmc">PMC4986668</ArticleId>
      <ArticleId IdType="doi">10.1093/jamia/ocv046</ArticleId>
      <ArticleId IdType="pii">ocv046</ArticleId>
    </ArticleIdList>
    <ReferenceList>
      <Reference>
        <Citation>Smith J. Something <i>italic</i> here. Lancet. 1983.</Citation>
        <ArticleIdList>
          <ArticleId IdType="pubmed">99999999</ArticleId>
          <ArticleId IdType="doi">10.9999/WRONG-DOI</ArticleId>
        </ArticleIdList>
      </Reference>
    </ReferenceList>
  </PubmedData>
</PubmedArticle></PubmedArticleSet>"""

# No MeshHeadingList, no KeywordList, no ReferenceList, no grants — all valid.
SPARSE_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet><PubmedArticle>
  <MedlineCitation><PMID>29036387</PMID>
    <Article><Journal><Title>J Am Med Inform Assoc</Title>
      <JournalIssue><PubDate><MedlineDate>2018 Winter</MedlineDate></PubDate></JournalIssue></Journal>
      <ArticleTitle>Uncovering exposures.</ArticleTitle></Article>
  </MedlineCitation>
  <PubmedData><ArticleIdList>
    <ArticleId IdType="pubmed">29036387</ArticleId>
  </ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""

PMC_XML = b"""<?xml version="1.0"?>
<article>
  <front><article-meta>
    <article-id pub-id-type="pmid">26041386</article-id>
    <article-id pub-id-type="pmc">4986668</article-id>
  </article-meta></front>
  <body>
    <p>A lead paragraph before any section.</p>
    <sec><title>INTRODUCTION</title>
      <p>Asthma was presented in 1983<xref ref-type="bibr" rid="r13">13</xref> and later
         corroborated<xref ref-type="bibr" rid="r14">14</xref>.</p>
    </sec>
    <sec><title>METHODS</title><p>We modeled <i>associations</i> by month.</p></sec>
  </body>
  <floats-group>
    <fig><label>Figure 1:</label><caption><p>Overview of the algorithm.</p></caption></fig>
    <table-wrap><label>Table 1:</label><caption><p>Demographics.</p></caption></table-wrap>
  </floats-group>
</article>"""

EMBARGOED_PMC_XML = b"""<?xml version="1.0"?>
<article><front><article-meta>
  <article-id pub-id-type="pmid">12345678</article-id>
</article-meta></front></article>"""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any test that reaches the network is a bug in the test, not a slow test."""
    def boom(*_a, **_k):
        raise AssertionError("test attempted a live NCBI request")
    monkeypatch.setattr(pubmed_fetch, "_get", boom)


# ------------------------------------------------------------------ input forms

@pytest.mark.parametrize("raw,expected", [
    ("https://pubmed.ncbi.nlm.nih.gov/26041386/", {"pmid": "26041386"}),
    ("https://pubmed.ncbi.nlm.nih.gov/26041386", {"pmid": "26041386"}),
    ("26041386", {"pmid": "26041386"}),
    ("PMC4986668", {"pmcid": "PMC4986668"}),
    ("pmc4986668", {"pmcid": "PMC4986668"}),
    ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4986668/", {"pmcid": "PMC4986668"}),
    ("10.1093/jamia/ocv046", {"doi": "10.1093/jamia/ocv046"}),
    ("https://doi.org/10.1093/jamia/ocv046", {"doi": "10.1093/jamia/ocv046"}),
])
def test_reference_forms_resolve(raw, expected):
    assert pubmed_fetch.parse_reference(raw) == expected


def test_pmc_url_is_not_mistaken_for_a_pmid():
    """A PMC URL contains digits that look exactly like a PMID."""
    assert "pmid" not in pubmed_fetch.parse_reference(
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4986668/")


@pytest.mark.parametrize("raw", ["", "   ", "https://example.com/foo", "not a reference"])
def test_unrecognised_references_raise(raw):
    with pytest.raises(PubMedError):
        pubmed_fetch.parse_reference(raw)


# ------------------------------------------------------------------- the traps

def test_article_ids_are_scoped_to_the_article_not_its_references():
    """The record's own doi, never a cited paper's."""
    rec = pubmed_fetch.parse_pubmed(ARTICLE_XML)
    assert rec["doi"] == "10.1093/jamia/ocv046"
    assert rec["pmcid"] == "PMC4986668"
    assert set(rec["ids"]) == {"pubmed", "pmc", "doi", "pii"}
    assert "10.9999/WRONG-DOI" not in rec["ids"].values()


def test_unscoped_id_search_would_have_picked_up_the_reference():
    """Pins WHY the scoped path exists — if this stops being true, so does the risk."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(ARTICLE_XML)
    loose = [e.text for e in root.findall(".//ArticleIdList/ArticleId")]
    assert "10.9999/WRONG-DOI" in loose
    assert len(loose) > len(root.findall(".//PubmedData/ArticleIdList/ArticleId"))


def test_inline_markup_is_not_truncated():
    """`.text` would return 'Risk of ' and 'Explore ' — both look like content."""
    rec = pubmed_fetch.parse_pubmed(ARTICLE_XML)
    assert rec["title"] == "Risk of P. falciparum infection by birth month."
    assert rec["abstract"][0]["text"] == "Explore seasonal effects."
    assert rec["references"][0]["citation"].startswith("Smith J. Something italic here.")


def test_structured_abstract_keeps_its_labels():
    rec = pubmed_fetch.parse_pubmed(ARTICLE_XML)
    assert [s["label"] for s in rec["abstract"]] == ["OBJECTIVE", "MATERIAL AND METHODS"]


def test_missing_mesh_keywords_and_references_are_tolerated():
    """PMID 29036387 is a real record with none of these."""
    rec = pubmed_fetch.parse_pubmed(SPARSE_XML)
    assert rec["mesh"] == [] and rec["keywords"] == [] and rec["references"] == []
    assert rec["abstract"] == [] and rec["grants"] == []
    assert rec["pmid"] == "29036387"


def test_medline_date_is_used_when_there_is_no_structured_year():
    assert pubmed_fetch.parse_pubmed(SPARSE_XML)["pub_date"] == "2018 Winter"


def test_collective_authors_survive_alongside_named_ones():
    rec = pubmed_fetch.parse_pubmed(ARTICLE_XML)
    assert [a["name"] for a in rec["authors"]] == ["Mary Regina Boland", "The SeaWAS Group"]
    assert rec["authors"][1]["collective"] is True


def test_major_mesh_topics_are_distinguished():
    mesh = pubmed_fetch.parse_pubmed(ARTICLE_XML)["mesh"]
    assert {m["descriptor"]: m["major"] for m in mesh} == {"Adolescent": False, "Seasons": True}
    assert mesh[1]["qualifiers"][0]["name"] == "statistics & numerical data"


def test_a_missing_article_raises_rather_than_returning_an_empty_record():
    with pytest.raises(PubMedError):
        pubmed_fetch.parse_pubmed(b"<PubmedArticleSet></PubmedArticleSet>")


# ----------------------------------------------------------------- PMC full text

def test_citation_superscripts_are_bracketed_not_glued_to_the_prose():
    """Without this, '1983.13' reads as a decimal number."""
    full = pubmed_fetch.parse_pmc(PMC_XML)
    intro = full["sections"][0]["paragraphs"][0]
    assert "1983.[13]" not in intro          # the period belongs to the sentence end
    assert "presented in 1983[13]" in intro
    assert "corroborated[14]" in intro


def test_lead_paragraphs_outside_any_section_are_kept():
    """A <p> directly under <body> belongs to no <sec> and is easy to drop."""
    assert pubmed_fetch.parse_pmc(PMC_XML)["intro_paragraphs"] == [
        "A lead paragraph before any section."]


def test_sections_and_float_labels():
    full = pubmed_fetch.parse_pmc(PMC_XML)
    assert [s["title"] for s in full["sections"]] == ["INTRODUCTION", "METHODS"]
    assert full["sections"][1]["paragraphs"] == ["We modeled associations by month."]
    assert full["figures"][0]["label"] == "Figure 1"     # trailing colon stripped
    assert full["tables"][0]["label"] == "Table 1"


def test_a_record_with_no_body_is_not_full_text():
    """An embargoed PMC record is a valid document with nothing in it."""
    assert pubmed_fetch.parse_pmc(EMBARGOED_PMC_XML) is None


# -------------------------------------------------------------------- rendering

def test_rendered_markdown_carries_the_record():
    rec = pubmed_fetch.parse_pubmed(ARTICLE_XML)
    md = pubmed_fetch.render_markdown(rec, pubmed_fetch.parse_pmc(PMC_XML))
    assert md.startswith("# Risk of P. falciparum infection by birth month.")
    assert "J Am Med Inform Assoc 22(5):1042-53 · 2015 Sep" in md
    assert "https://doi.org/10.1093/jamia/ocv046" in md
    assert "**Objective.** Explore seasonal effects." in md
    assert "### INTRODUCTION" in md
    # Commas appear INSIDE descriptors, so the separator cannot be a comma.
    assert "**MeSH:** Adolescent; Seasons*" in md


def test_absent_full_text_is_stated_not_silently_omitted():
    rec = pubmed_fetch.parse_pubmed(SPARSE_XML)
    md = pubmed_fetch.render_markdown(rec, None)
    assert "Full text not retrievable" in md
    assert "No abstract in the PubMed record" in md
    assert "MeSH" not in md


def test_no_marker_is_printed_when_the_fetch_fails(capsys, monkeypatch):
    """Callers chain on OUTPUT_DIR:. Printing it after a failure is worse than failing."""
    monkeypatch.setattr(pubmed_fetch, "fetch", lambda *_a, **_k: (_ for _ in ()).throw(
        PubMedError("boom")))
    assert pubmed_fetch.main(["26041386", "/tmp/should-not-be-created"]) == 1
    out = capsys.readouterr()
    assert "OUTPUT_DIR:" not in out.out
    assert "ERROR: boom" in out.err


# ------------------------------------------------- floats nested inside the prose

INLINE_FLOAT_PMC_XML = b"""<?xml version="1.0"?>
<article>
  <front><article-meta>
    <article-id pub-id-type="pmid">26041386</article-id>
  </article-meta></front>
  <body>
    <sec><title>RESULTS</title>
      <p>We found 55 conditions.
        <table-wrap id="T2"><label>Table 2:</label>
          <caption><p>Conditions by birth month.</p></caption>
          <table>
            <thead><tr><th>Condition</th><th>N</th><th>High</th></tr></thead>
            <tbody>
              <tr><td>Atrial fibrillation</td><td>48 961</td><td>March</td></tr>
              <tr><td>Essential hypertension</td><td>269 913</td><td>January</td></tr>
            </tbody>
          </table>
        </table-wrap>
        Nine of them were cardiovascular.</p>
      <p>An unrelated paragraph.
        <fig id="F1"><label>Figure 3:</label><caption><p>The SeaWAS pipeline.</p></caption></fig>
      </p>
    </sec>
  </body>
</article>"""


def test_a_float_nested_in_a_paragraph_does_not_leak_into_the_prose():
    """JATS nests <table-wrap> inside <p>. Flattening produces
    'Atrial fibrillation48 961March' glued into the sentence — corrupted data
    that reads as prose, with nothing to signal it went wrong."""
    full = pubmed_fetch.parse_pmc(INLINE_FLOAT_PMC_XML)
    prose = " ".join(p for s in full["sections"] for p in s["paragraphs"])
    assert "48 961" not in prose
    assert "Atrial fibrillation" not in prose
    assert "SeaWAS pipeline" not in prose
    assert "Conditions by birth month" not in prose


def test_prose_on_both_sides_of_a_detached_float_survives():
    """The float's tail is real sentence text and must be handed back."""
    full = pubmed_fetch.parse_pmc(INLINE_FLOAT_PMC_XML)
    paras = full["sections"][0]["paragraphs"]
    assert "We found 55 conditions." in paras[0]
    assert "Nine of them were cardiovascular." in paras[0]


def test_a_caption_is_not_also_counted_as_a_body_paragraph():
    """`.//p` matches the caption's own <p>, so an un-detached caption is
    captured twice — once inline, once as a paragraph of its own."""
    full = pubmed_fetch.parse_pmc(INLINE_FLOAT_PMC_XML)
    paras = full["sections"][0]["paragraphs"]
    assert len(paras) == 2, paras


def test_table_grids_are_captured_as_rows():
    full = pubmed_fetch.parse_pmc(INLINE_FLOAT_PMC_XML)
    assert full["tables"][0]["rows"] == [
        ["Condition", "N", "High"],
        ["Atrial fibrillation", "48 961", "March"],
        ["Essential hypertension", "269 913", "January"],
    ]


def test_a_table_renders_as_a_markdown_table_not_a_bullet():
    rec = pubmed_fetch.parse_pubmed(ARTICLE_XML)
    md = pubmed_fetch.render_markdown(rec, pubmed_fetch.parse_pmc(INLINE_FLOAT_PMC_XML))
    assert "| Condition | N | High |" in md
    assert "| Atrial fibrillation | 48 961 | March |" in md


def test_floats_hoisted_into_floats_group_are_still_found():
    """The other PMC layout: floats live outside <body> entirely."""
    full = pubmed_fetch.parse_pmc(PMC_XML)
    assert [f["label"] for f in full["figures"]] == ["Figure 1"]
    assert [t["label"] for t in full["tables"]] == ["Table 1"]


def test_a_caption_only_table_says_so_rather_than_rendering_an_empty_grid():
    rec = pubmed_fetch.parse_pubmed(ARTICLE_XML)
    md = pubmed_fetch.render_markdown(rec, pubmed_fetch.parse_pmc(PMC_XML))
    assert "*(table grid not present in the PMC record)*" in md


def test_a_pipe_in_a_cell_does_not_break_the_markdown_table():
    rows = [["a", "b|c"], ["d", "e"]]
    assert r"b\|c" in "\n".join(pubmed_fetch._render_table(rows))


def test_ragged_rows_are_padded_not_truncated():
    """A row shorter than the header must keep its cells, not lose them."""
    out = pubmed_fetch._render_table([["a", "b", "c"], ["x"]])
    assert out[-1] == "| x |  |  |"


# ------------------------------------------------------------------- CLI parsing

def test_an_unknown_flag_is_rejected_rather_than_used_as_a_directory(capsys, monkeypatch):
    """`--output-dir X` once created a directory literally named "--output-dir".
    A wrong destination that exits 0 is worse than any crash."""
    monkeypatch.setattr(pubmed_fetch, "fetch",
                        lambda *_a, **_k: pytest.fail("fetch ran on a bad argv"))
    assert pubmed_fetch.main(["26041386", "--nonsense", "/tmp/x"]) == 2
    assert "unknown option --nonsense" in capsys.readouterr().err


def test_output_dir_flag_and_positional_agree(monkeypatch):
    seen = []
    monkeypatch.setattr(pubmed_fetch, "fetch",
                        lambda ref, out: seen.append((ref, out)) or Path(out))
    pubmed_fetch.main(["26041386", "--output-dir", "/tmp/a"])
    pubmed_fetch.main(["26041386", "/tmp/a"])
    assert seen[0] == seen[1] == ("26041386", Path("/tmp/a"))


def test_a_flag_with_no_value_does_not_silently_default(capsys):
    assert pubmed_fetch.main(["26041386", "--output-dir"]) == 2
    assert "needs a directory" in capsys.readouterr().err


def test_no_arguments_is_a_usage_error(capsys):
    assert pubmed_fetch.main([]) == 2
    assert "usage:" in capsys.readouterr().err


# ------------------------------------------------------------------ table spans

SPANNED_TABLE_XML = b"""<?xml version="1.0"?>
<article><front><article-meta>
  <article-id pub-id-type="pmid">26041386</article-id>
</article-meta></front>
<body><sec><title>RESULTS</title><p>Text.
  <table-wrap><label>Table 2</label><caption><p>Spanned.</p></caption>
    <table>
      <thead>
        <tr><th rowspan="2">Condition</th><th rowspan="2">N</th><th colspan="2">Birth Month Risk</th></tr>
        <tr><th>High</th><th>Low</th></tr>
      </thead>
      <tbody><tr><td>Atrial fibrillation</td><td>48 961</td><td>March</td><td>October</td></tr></tbody>
    </table>
  </table-wrap></p></sec></body></article>"""


def test_rowspan_does_not_shift_the_second_header_row_left():
    """Appending cells in document order puts High/Low under Condition and N —
    every column mislabelled, in a table that still looks well-formed."""
    rows = pubmed_fetch.parse_pmc(SPANNED_TABLE_XML)["tables"][0]["rows"]
    assert rows[1] == ["", "", "High", "Low"]


def test_colspan_reserves_the_columns_it_covers():
    rows = pubmed_fetch.parse_pmc(SPANNED_TABLE_XML)["tables"][0]["rows"]
    assert rows[0] == ["Condition", "N", "Birth Month Risk", ""]


def test_every_row_of_a_spanned_table_is_the_same_width():
    rows = pubmed_fetch.parse_pmc(SPANNED_TABLE_XML)["tables"][0]["rows"]
    assert {len(r) for r in rows} == {4}


def test_data_lands_under_the_header_it_belongs_to():
    rows = pubmed_fetch.parse_pmc(SPANNED_TABLE_XML)["tables"][0]["rows"]
    high = rows[1].index("High")
    assert rows[2][high] == "March"
    assert rows[2][rows[1].index("Low")] == "October"


def test_a_malformed_span_attribute_does_not_crash_the_parse():
    xml = SPANNED_TABLE_XML.replace(b'colspan="2"', b'colspan="oops"')
    assert pubmed_fetch.parse_pmc(xml)["tables"][0]["rows"]
