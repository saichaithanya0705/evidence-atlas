"""Focused tests for the real PubMed ingestion bridge."""

from scripts.ingest_pubmed_phrases import parse_articles, select_pmids
from pipelines.preprocess import resolve_columns


def test_select_pmids_never_exceeds_limit_when_intersection_is_large():
    mapping = {
        "first": ["1", "2", "3", "4"],
        "second": ["4", "3", "2", "1", "5"],
    }

    selected = select_pmids(mapping, limit=2)

    assert selected == ["1", "2"]


def test_parse_articles_preserves_raw_date_and_all_publication_types():
    payload = b"""<?xml version="1.0"?>
    <PubmedArticleSet><PubmedArticle><MedlineCitation>
      <PMID>12345</PMID><Article>
        <ArticleTitle>Trial title</ArticleTitle>
        <Abstract><AbstractText Label="RESULTS">A useful result.</AbstractText></Abstract>
        <Journal><Title>Journal</Title><JournalIssue><PubDate>
          <Year>2024</Year><Month>Jan</Month><Day>3</Day>
        </PubDate></JournalIssue></Journal>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
          <PublicationType>Randomized Controlled Trial</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation><PubmedData><ArticleIdList>
      <ArticleId IdType="doi">10.1/example</ArticleId>
    </ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""

    record = parse_articles(payload)[0]

    assert record["publication_date"] == "2024-Jan-3"
    assert record["publication_date_raw"] == "2024 Jan 3"
    assert record["publication_types"] == "Journal Article; Randomized Controlled Trial"
    assert record["study_type"] == "Journal Article"


def test_preprocessing_prefers_auditable_source_metadata_columns():
    mapping = resolve_columns([
        "pmid", "title", "abstract", "publication_date", "publication_date_raw",
        "study_type", "publication_types",
    ])

    assert mapping["pubdate"] == "publication_date_raw"
    assert mapping["pub_type"] == "publication_types"
