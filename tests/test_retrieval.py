"""
test_retrieval.py — evidence chunking, lexical retrieval, and the
retrieve_evidence tool tests.
"""

from __future__ import annotations

import json

import pytest
from backend.schemas import SchemeRecord, EligibilityCriteria, Criterion, build_chunks
from backend.tools import retrieve_evidence as retrieve_evidence_tool


# ---------------------------------------------------------------------------
# Chunk building
# ---------------------------------------------------------------------------

def _sample_scheme() -> SchemeRecord:
    return SchemeRecord(
        id="test-scheme",
        name="Test Scholarship",
        description="A scholarship for test students.",
        criteria=EligibilityCriteria(min_percentage=55.0, notes="Test notes."),
        criterion_list=[
            Criterion(field="education_level", operator="in", value=["UG", "PG"]),
            Criterion(field="min_percentage", operator="gte", value=55.0),
        ],
        documents=["Aadhaar card", "Marksheet"],
        application_steps=["Register", "Apply"],
        deadline="2026-12-31",
        source_url="https://example.org/test",
        verified=True,
        last_checked="2026-09-01",
        tags=["test", "UG"],
        description_snippet="A scholarship for test students.",
    )


class TestBuildChunks:
    def test_chunks_cover_all_sections(self):
        chunks = build_chunks(_sample_scheme())
        types = {c["chunk_type"] for c in chunks}
        assert {"summary", "criteria", "documents", "steps", "deadline"} <= types

    def test_summary_chunk_contains_name_and_description(self):
        chunks = build_chunks(_sample_scheme())
        summary = [c for c in chunks if c["chunk_type"] == "summary"][0]
        assert "Test Scholarship" in summary["text"]
        assert "test students" in summary["text"]

    def test_criteria_chunk_contains_operator_labels(self):
        chunks = build_chunks(_sample_scheme())
        criteria = [c for c in chunks if c["chunk_type"] == "criteria"][0]
        assert "education_level" in criteria["text"]
        assert "min_percentage" in criteria["text"]

    def test_all_chunks_carry_scheme_context(self):
        for chunk in build_chunks(_sample_scheme()):
            assert chunk["scheme_id"] == "test-scheme"
            assert chunk["source_url"] == "https://example.org/test"

    def test_empty_documents_produce_no_chunk(self):
        scheme = SchemeRecord(
            id="s", name="S", description="D",
            criteria=EligibilityCriteria(),
            documents=[],
        )
        types = {c["chunk_type"] for c in build_chunks(scheme)}
        assert "documents" not in types


# ---------------------------------------------------------------------------
# Repository retrieval
# ---------------------------------------------------------------------------

class TestRetrieval:
    def test_retrieve_returns_relevant_chunks(self, repository):
        chunks = repository.retrieve("SC scholarship class 10", k=3)
        assert len(chunks) > 0
        for chunk in chunks:
            assert "scheme_id" in chunk
            assert "text" in chunk
            assert "source_url" in chunk

    def test_retrieve_respects_k(self, repository):
        chunks = repository.retrieve("scholarship", k=2)
        assert len(chunks) <= 2

    def test_retrieve_returns_empty_for_no_match(self, repository):
        chunks = repository.retrieve("xyznonexistent12345", k=5)
        assert chunks == []

    def test_chunks_built_at_load_time(self, repository):
        assert repository.count() > 0
        assert len(repository._chunks) > repository.count()


# ---------------------------------------------------------------------------
# retrieve_evidence tool
# ---------------------------------------------------------------------------

class TestRetrieveEvidenceTool:
    def test_tool_returns_structured_results(self, repository):
        result = retrieve_evidence_tool(repository, query="SC scholarship", k=3)
        assert result["result_count"] > 0
        assert len(result["results"]) <= 3
        for chunk in result["results"]:
            assert chunk["scheme_id"]
            assert chunk["text"]

    def test_tool_validates_empty_query(self, repository):
        result = retrieve_evidence_tool(repository, query="  ")
        assert result.get("error") is True

    def test_tool_clamps_k(self, repository):
        result = retrieve_evidence_tool(repository, query="scholarship", k=999)
        assert not result.get("error")
        assert len(result["results"]) <= 20


# ---------------------------------------------------------------------------
# App-level sources population from retrieve_evidence
# ---------------------------------------------------------------------------

class TestRetrievalSources:
    def test_chat_sources_populated_from_retrieve(self, client, mock_provider):
        from tests.helpers import make_function_call_response, make_text_response
        mock_provider.generate.side_effect = [
            make_function_call_response("retrieve_evidence", {"query": "SC scholarship"}),
            make_text_response("Based on the evidence..."),
        ]
        data = client.post("/api/chat", json={"message": "SC scholarships"}).get_json()
        assert data.get("sources")
        for source in data["sources"]:
            assert source["id"]
            assert source["url"].startswith("https://")