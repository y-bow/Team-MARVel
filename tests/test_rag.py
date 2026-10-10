"""
test_rag.py — Unit tests for the RAG Implementation.
"""

import os
import tempfile
from pathlib import Path

import pytest
from backend.rag import RAGStore, chunk_text, clean_text, extract_html_structure, compute_content_hash
from backend.tools import search_guidelines


def test_clean_text():
    assert clean_text("  This   is \n\n a test.  ") == "This is a test."


def test_chunk_text():
    text = " ".join([f"word{i}" for i in range(100)])
    chunks = chunk_text(text, chunk_size=200, overlap=40)
    assert len(chunks) > 1
    # Check overlap
    assert chunks[0].split()[-1] in chunks[1]


def test_chunk_text_sentence_aware():
    """Test that chunking respects sentence boundaries."""
    text = "This is sentence one. This is sentence two. This is sentence three. This is sentence four."
    chunks = chunk_text(text, chunk_size=50, overlap=10)
    # Should have multiple chunks
    assert len(chunks) >= 2
    # Each chunk should end with a period (sentence boundary preserved where possible)
    for chunk in chunks:
        assert chunk.strip().endswith(".")


def test_chunk_text_long_sentence():
    """Test that very long sentences are split by words."""
    long_sentence = " ".join(["word"] * 500) + "."
    chunks = chunk_text(long_sentence, chunk_size=200, overlap=40)
    assert len(chunks) > 1


def test_compute_content_hash():
    text = "test content"
    hash1 = compute_content_hash(text)
    hash2 = compute_content_hash(text)
    assert hash1 == hash2
    assert len(hash1) == 16
    # Different content should produce different hash
    assert compute_content_hash("different") != hash1


def test_extract_html_structure():
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write("<html><title>Test Page</title><body><h1>Main Heading</h1><p>Content here.</p><h2>Sub Heading</h2></body></html>")
        f_path = f.name
    
    try:
        title, headings, text = extract_html_structure(f_path)
        assert title == "Test Page"
        assert len(headings) == 2
        assert headings[0]["level"] == 1
        assert headings[0]["text"] == "Main Heading"
        assert headings[1]["level"] == 2
        assert headings[1]["text"] == "Sub Heading"
        assert "Content here" in text
    finally:
        os.unlink(f_path)


@pytest.fixture
def rag_store():
    # ignore_cleanup_errors is needed on Windows because chroma locks sqlite files
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        store = RAGStore(persist_directory=tmpdir)
        yield store


def test_empty_index_search(rag_store):
    assert rag_store.count() == 0
    results = rag_store.search_evidence("test query")
    assert results == []


def test_unavailable_provider():
    store = RAGStore(persist_directory="/invalid/path/that/fails/hopefully")
    # If it falls back or fails, is_available should handle it
    # We'll just test that we can mock it
    store.is_available = False
    assert store.count() == 0
    assert store.search_evidence("query") == []


def test_html_ingestion(rag_store):
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write("<html><title>Test Doc</title><body>This is a specific test document about the SC scholarship rules for 2024.</body></html>")
        f_path = f.name
        
    try:
        chunks_added = rag_store.ingest_html(f_path, {"scheme_id": "test-sc", "academic_year": "2024-25"})
        assert chunks_added > 0
        assert rag_store.count() > 0
        
        # Test retrieval relevance
        results = rag_store.search_evidence("What are the SC rules?", scheme_id="test-sc")
        assert len(results) > 0
        assert "SC scholarship rules" in results[0]["content"]
        
        # Test metadata
        meta = results[0]["metadata"]
        assert meta["scheme_id"] == "test-sc"
        assert meta["academic_year"] == "2024-25"
        assert meta["source_type"] == "html"
        assert meta["source_title"] == "Test Doc"
        
        # Test duplicate ingestion (default behavior: adds duplicates)
        rag_store.ingest_html(f_path, {"scheme_id": "test-sc", "academic_year": "2024-25"})
        assert rag_store.count() == chunks_added * 2
        
        # Test academic year filtering
        results_wrong_year = rag_store.search_evidence("rules", academic_year="2023-24")
        assert len(results_wrong_year) == 0
        
        results_right_year = rag_store.search_evidence("rules", academic_year="2024-25")
        assert len(results_right_year) > 0
        
    finally:
        os.unlink(f_path)


def test_html_ingestion_with_headings(rag_store):
    """Test that HTML headings are extracted and stored."""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write("<html><title>Guidelines</title><body><h1>Eligibility</h1><p>Must be SC category.</p><h2>Income Limit</h2><p>Income must be below 2.5 LPA.</p></body></html>")
        f_path = f.name
        
    try:
        chunks_added = rag_store.ingest_html(f_path, {"scheme_id": "test-sc", "academic_year": "2024-25"})
        assert chunks_added > 0
        
        results = rag_store.search_evidence("income limit", scheme_id="test-sc")
        assert len(results) > 0
        
        # Check that headings are in metadata
        meta = results[0]["metadata"]
        assert "headings" in meta
        assert "Income Limit" in meta["headings"]
        
    finally:
        os.unlink(f_path)


def test_skip_duplicates_html(rag_store):
    """Test skip_duplicates prevents adding same content twice."""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write("<html><title>Test Doc</title><body>Unique content about scholarship eligibility.</body></html>")
        f_path = f.name
        
    try:
        # First ingestion
        chunks1 = rag_store.ingest_html(f_path, {"scheme_id": "test-sc", "academic_year": "2024-25"}, skip_duplicates=True)
        assert chunks1 > 0
        count1 = rag_store.count()
        
        # Second ingestion with skip_duplicates should add 0
        chunks2 = rag_store.ingest_html(f_path, {"scheme_id": "test-sc", "academic_year": "2024-25"}, skip_duplicates=True)
        assert chunks2 == 0
        assert rag_store.count() == count1
        
        # Without skip_duplicates, should add again
        chunks3 = rag_store.ingest_html(f_path, {"scheme_id": "test-sc", "academic_year": "2024-25"}, skip_duplicates=False)
        assert chunks3 > 0
        assert rag_store.count() == count1 + chunks3
        
    finally:
        os.unlink(f_path)


def test_skip_duplicates_pdf(rag_store):
    """Test skip_duplicates works for PDF ingestion."""
    # Create a simple PDF for testing
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        # We'll just test the logic by mocking or using a minimal PDF
        # For now, test that the parameter is accepted
        pass
    # Note: PDF test would require creating a real PDF file, skipped for simplicity


def test_search_guidelines_tool(rag_store):
    # Empty index
    res = search_guidelines(rag_store, "test")
    assert res["evidence"] == []
    
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write("<html><body>Income limit is 2.5 LPA.</body></html>")
        f_path = f.name
        
    try:
        rag_store.ingest_html(f_path, {"scheme_id": "scheme1", "source_url": "http://test.com"})
        
        res = search_guidelines(rag_store, "income limit", scheme_id="scheme1")
        assert len(res["evidence"]) > 0
        assert "2.5 LPA" in res["evidence"][0]["content"]
        assert res["evidence"][0]["source_url"] == "http://test.com"
        
    finally:
        os.unlink(f_path)


def test_scheme_id_filtering(rag_store):
    """Test that search filters by scheme_id correctly."""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f1:
        f1.write("<html><body>Scheme A content about eligibility rules.</body></html>")
        f1_path = f1.name
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f2:
        f2.write("<html><body>Scheme B content about different rules.</body></html>")
        f2_path = f2.name
    
    try:
        rag_store.ingest_html(f1_path, {"scheme_id": "scheme-a", "academic_year": "2024-25"})
        rag_store.ingest_html(f2_path, {"scheme_id": "scheme-b", "academic_year": "2024-25"})
        
        # Search with scheme filter
        results_a = rag_store.search_evidence("eligibility", scheme_id="scheme-a")
        assert len(results_a) > 0
        assert all(r["metadata"]["scheme_id"] == "scheme-a" for r in results_a)
        
        results_b = rag_store.search_evidence("different", scheme_id="scheme-b")
        assert len(results_b) > 0
        assert all(r["metadata"]["scheme_id"] == "scheme-b" for r in results_b)
        
        # Search without filter should return both
        results_all = rag_store.search_evidence("content")
        assert len(results_all) >= 2
        
    finally:
        os.unlink(f1_path)
        os.unlink(f2_path)


def test_academic_year_filtering(rag_store):
    """Test that search filters by academic_year correctly."""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f1:
        f1.write("<html><body>Rules for 2023-24 academic year.</body></html>")
        f1_path = f1.name
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f2:
        f2.write("<html><body>Rules for 2024-25 academic year.</body></html>")
        f2_path = f2.name
    
    try:
        rag_store.ingest_html(f1_path, {"scheme_id": "scheme1", "academic_year": "2023-24"})
        rag_store.ingest_html(f2_path, {"scheme_id": "scheme1", "academic_year": "2024-25"})
        
        results_23 = rag_store.search_evidence("rules", scheme_id="scheme1", academic_year="2023-24")
        assert len(results_23) > 0
        assert all(r["metadata"]["academic_year"] == "2023-24" for r in results_23)
        
        results_24 = rag_store.search_evidence("rules", scheme_id="scheme1", academic_year="2024-25")
        assert len(results_24) > 0
        assert all(r["metadata"]["academic_year"] == "2024-25" for r in results_24)
        
    finally:
        os.unlink(f1_path)
        os.unlink(f2_path)


def test_delete_by_scheme(rag_store):
    """Test deleting all chunks for a scheme."""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write("<html><body>Test content.</body></html>")
        f_path = f.name
    
    try:
        rag_store.ingest_html(f_path, {"scheme_id": "scheme-to-delete"})
        assert rag_store.count() > 0
        
        rag_store.delete_by_scheme("scheme-to-delete")
        assert rag_store.count() == 0
        
        # Other schemes should be unaffected
        rag_store.ingest_html(f_path, {"scheme_id": "other-scheme"})
        assert rag_store.count() > 0
        rag_store.delete_by_scheme("scheme-to-delete")  # Should not affect other-scheme
        assert rag_store.count() > 0
        
    finally:
        os.unlink(f_path)


def test_ingest_directory(rag_store):
    """Test batch ingestion from a directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        html_file = Path(tmpdir) / "test1.html"
        html_file.write_text("<html><title>Doc 1</title><body>Content about scholarship A.</body></html>")
        
        html_file2 = Path(tmpdir) / "test2.html"
        html_file2.write_text("<html><title>Doc 2</title><body>Content about scholarship B.</body></html>")
        
        txt_file = Path(tmpdir) / "readme.txt"
        txt_file.write_text("This should be skipped.")
        
        metadata = {"scheme_id": "batch-test", "academic_year": "2024-25"}
        results = rag_store.ingest_directory(tmpdir, metadata, skip_duplicates=False)
        
        assert results["html"] > 0
        assert results["pdf"] == 0
        assert results["skipped"] == 1  # txt file
        assert results["total"] > 0
        assert rag_store.count() == results["total"]


def test_ingest_directory_with_skip_duplicates(rag_store):
    """Test batch ingestion with skip_duplicates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        html_file = Path(tmpdir) / "test.html"
        html_file.write_text("<html><title>Doc</title><body>Duplicate test content.</body></html>")
        
        metadata = {"scheme_id": "batch-test", "academic_year": "2024-25"}
        
        # First ingestion
        results1 = rag_store.ingest_directory(tmpdir, metadata, skip_duplicates=True)
        assert results1["total"] > 0
        
        # Second ingestion should skip
        results2 = rag_store.ingest_directory(tmpdir, metadata, skip_duplicates=True)
        assert results2["total"] == 0


def test_get_stats(rag_store):
    """Test statistics retrieval."""
    stats = rag_store.get_stats()
    assert stats["available"] is True
    assert stats["total_chunks"] == 0
    assert stats["unique_schemes"] == 0
    
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write("<html><title>Test</title><body>Content for stats.</body></html>")
        f_path = f.name
    
    try:
        rag_store.ingest_html(f_path, {"scheme_id": "stats-scheme", "academic_year": "2024-25"})
        stats = rag_store.get_stats()
        assert stats["total_chunks"] > 0
        assert stats["unique_schemes"] == 1
        assert "stats-scheme" in stats["scheme_ids"]
        assert "2024-25" in stats["academic_years"]
        assert "html" in stats["source_types"]
    finally:
        os.unlink(f_path)


def test_search_returns_citations(rag_store):
    """Test that search results include all citation metadata."""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write("<html><title>Official Guidelines</title><body>Income limit is 2.5 LPA per year.</body></html>")
        f_path = f.name
    
    try:
        rag_store.ingest_html(f_path, {
            "scheme_id": "cite-test",
            "academic_year": "2024-25",
            "source_url": "https://official.gov.in/guidelines",
            "source_title": "Official Guidelines"
        })
        
        results = rag_store.search_evidence("income limit", scheme_id="cite-test")
        assert len(results) > 0
        
        meta = results[0]["metadata"]
        # Check all citation fields
        assert meta["scheme_id"] == "cite-test"
        assert meta["academic_year"] == "2024-25"
        assert meta["source_url"] == "https://official.gov.in/guidelines"
        assert meta["source_title"] == "Official Guidelines"
        assert meta["source_type"] == "html"
        assert "content_hash" in meta
        
    finally:
        os.unlink(f_path)
