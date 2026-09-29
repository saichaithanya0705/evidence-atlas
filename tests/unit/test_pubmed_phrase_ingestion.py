"""Focused tests for the real PubMed ingestion bridge."""

import json
from urllib.error import HTTPError

import scripts.ingest_pubmed_phrases as ingestion
from scripts.ingest_pubmed_phrases import (
    parse_articles,
    select_pmids,
)
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


def test_parse_europe_pmc_results_maps_core_pubmed_metadata():
    payload = json.dumps({
        "resultList": {
            "result": [{
                "pmid": "98765",
                "title": "Fallback trial",
                "abstractText": "<h4>Results</h4>A useful <i>clinical</i> result.",
                "authorString": "Example A, Researcher B.",
                "journalInfo": {
                    "dateOfPublication": "2024 Jan",
                    "yearOfPublication": 2024,
                    "journal": {"title": "Fallback Journal"},
                },
                "firstPublicationDate": "2024-01-03",
                "pubTypeList": {"pubType": ["Journal Article", "Clinical Trial"]},
                "meshHeadingList": {
                    "meshHeading": [{"descriptorName": "Humans"}, {"descriptorName": "Kidney Diseases"}]
                },
                "keywordList": {"keyword": ["SGLT2", "outcomes"]},
                "doi": "10.1/fallback",
            }]
        }
    }).encode("utf-8")

    record = ingestion.parse_europe_pmc_results(payload)[0]

    assert record == {
        "pmid": "98765",
        "title": "Fallback trial",
        "abstract": "Results A useful clinical result.",
        "authors": "Example A, Researcher B.",
        "journal": "Fallback Journal",
        "publication_date": "2024-01-03",
        "publication_date_raw": "2024 Jan",
        "year": "2024",
        "study_type": "Journal Article",
        "publication_types": "Journal Article; Clinical Trial",
        "mesh_terms": "Humans; Kidney Diseases",
        "keywords": "SGLT2; outcomes",
        "doi": "10.1/fallback",
    }


def test_fetch_records_falls_back_to_europe_pmc_after_ncbi_forbidden(monkeypatch):
    def forbidden(_pmids, _email):
        raise HTTPError("https://example.test", 403, "Forbidden", {}, None)

    expected = [{"pmid": "98765"}]
    monkeypatch.setattr(ingestion, "fetch_pubmed_xml", forbidden)
    monkeypatch.setattr(ingestion, "fetch_europe_pmc_records", lambda _pmids: expected)

    records, source = ingestion.fetch_records(["98765"], "")

    assert records == expected
    assert source == "Europe PMC REST API"


def test_ingestion_checkpoint_restores_completed_batches(tmp_path):
    checkpoint = tmp_path / "ingestion.jsonl"
    selected = ["1", "2", "3"]
    batch_records = [{"pmid": "1", "title": "First"}]

    ingestion.append_checkpoint_batch(
        checkpoint,
        selected,
        ["1", "2"],
        batch_records,
        ingestion.EUROPE_PMC_SOURCE,
    )
    records, completed, source = ingestion.load_ingestion_checkpoint(checkpoint, selected)

    assert records == batch_records
    assert completed == {"1", "2"}
    assert source == ingestion.EUROPE_PMC_SOURCE


def test_europe_pmc_fetch_survives_extended_transient_outage(monkeypatch):
    attempts = 0

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"resultList":{"result":[]}}'

    def flaky_urlopen(_request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts <= 4:
            raise HTTPError("https://example.test", 503, "Unavailable", {}, None)
        return Response()

    monkeypatch.setattr(ingestion, "urlopen", flaky_urlopen)
    monkeypatch.setattr(ingestion.time, "sleep", lambda _seconds: None)

    records = ingestion.fetch_europe_pmc_records(["98765"])

    assert records == []


def test_preprocessing_prefers_auditable_source_metadata_columns():
    mapping = resolve_columns([
        "pmid", "title", "abstract", "publication_date", "publication_date_raw",
        "study_type", "publication_types",
    ])

    assert mapping["pubdate"] == "publication_date_raw"
    assert mapping["pub_type"] == "publication_types"
