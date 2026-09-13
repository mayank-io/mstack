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
