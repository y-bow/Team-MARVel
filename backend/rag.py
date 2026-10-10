"""
rag.py — EduSaarthi AI RAG Implementation.

Handles document ingestion, text splitting, embeddings generation,
and vector storage/retrieval using ChromaDB.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
    """Clean extracted text by removing extra whitespace."""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def compute_content_hash(text: str) -> str:
    """Compute a SHA256 hash of the text content for deduplication."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """Split text into overlapping chunks using sentence-aware splitting."""
    if not text:
        return []
        
    # Split into sentences first (simple regex-based)
    # This preserves sentence boundaries better than word-based chunking
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    chunks = []
    current_chunk = ""
    current_size = 0
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
            
        sentence_size = len(sentence)
        
        # If a single sentence is larger than chunk_size, fall back to word-based
        if sentence_size > chunk_size:
            # Flush current chunk
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
                current_size = 0
            # Split the long sentence by words
            words = sentence.split()
            word_chunk_size = chunk_size // 5
            word_overlap = overlap // 5
            if word_chunk_size <= word_overlap:
                word_chunk_size = 200
                word_overlap = 40
            i = 0
            while i < len(words):
                chunk = " ".join(words[i : i + word_chunk_size])
                chunks.append(chunk)
                i += word_chunk_size - word_overlap
            continue
        
        # If adding this sentence would exceed chunk_size, start a new chunk
        if current_size + sentence_size + 1 > chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            # Start new chunk with overlap from the end of previous chunk
            overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
            current_chunk = overlap_text + " " + sentence
            current_size = len(current_chunk)
        else:
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence
            current_size = len(current_chunk)
    
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    return chunks


def extract_html_structure(filepath: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract title, headings, and text from HTML while preserving structure."""
    with open(filepath, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')
    
    # Extract title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    
    # Extract headings with their hierarchy
    headings = []
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        level = int(heading.name[1])
        text = heading.get_text(strip=True)
        if text:
            headings.append({
                "level": level,
                "text": text
            })
    
    # Get full text
    text = soup.get_text(separator=' ')
    text = clean_text(text)
    
    return title, headings, text


class RAGStore:
    def __init__(self, persist_directory: str, embedding_model_name: str = "all-MiniLM-L6-v2"):
        """Initialize ChromaDB client and collection."""
        self.persist_directory = persist_directory
        self.embedding_model_name = embedding_model_name
        
        # We ensure the path exists
        os.makedirs(self.persist_directory, exist_ok=True)
        
        try:
            self.client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False)
            )
            self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=self.embedding_model_name
            )
            self.collection = self.client.get_or_create_collection(
                name="scholarship_evidence",
                embedding_function=self.embedding_function
            )
            self.is_available = True
        except Exception as e:
            logger.error(f"Failed to initialize RAG store: {e}")
            self.is_available = False

    def count(self) -> int:
        if not self.is_available:
            return 0
        return self.collection.count()

    def _chunk_exists(self, content_hash: str, scheme_id: str) -> bool:
        """Check if a chunk with the same content hash already exists for this scheme."""
        if not self.is_available:
            return False
        try:
            results = self.collection.get(
                where={"$and": [{"content_hash": content_hash}, {"scheme_id": scheme_id}]},
                limit=1
            )
            return len(results.get('ids', [])) > 0
        except Exception:
            return False

    def ingest_pdf(self, filepath: str, metadata: dict, skip_duplicates: bool = False) -> int:
        """Extract text from a PDF, chunk it, and add to the vector store.
        
        Args:
            filepath: Path to the PDF file
            metadata: Dictionary with scheme_id, academic_year, source_url, source_title, etc.
            skip_duplicates: If True, skip chunks that already exist (based on content hash)
            
        Returns:
            Number of chunks added
        """
        if not self.is_available:
            raise RuntimeError("RAG store is unavailable.")
        if not PdfReader:
            raise RuntimeError("pypdf is not installed.")
            
        reader = PdfReader(filepath)
        chunks_added = 0
        scheme_id = metadata.get('scheme_id', 'doc')
        
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text:
                continue
                
            text = clean_text(text)
            chunks = chunk_text(text)
            
            for j, chunk in enumerate(chunks):
                content_hash = compute_content_hash(chunk)
                
                # Check for duplicates if requested
                if skip_duplicates and self._chunk_exists(content_hash, scheme_id):
                    logger.debug(f"Skipping duplicate chunk: {scheme_id}-page{i+1}-chunk{j}")
                    continue
                
                chunk_id = f"{scheme_id}-page{i+1}-chunk{j}-{uuid.uuid4().hex[:6]}"
                
                chunk_meta = metadata.copy()
                chunk_meta["source_type"] = "pdf"
                chunk_meta["page_number"] = i + 1
                chunk_meta["content_hash"] = content_hash
                
                self.collection.add(
                    documents=[chunk],
                    metadatas=[chunk_meta],
                    ids=[chunk_id]
                )
                chunks_added += 1
                
        return chunks_added

    def ingest_html(self, filepath: str, metadata: dict, skip_duplicates: bool = False) -> int:
        """Extract text from an HTML file, chunk it, and add to the vector store.
        
        Args:
            filepath: Path to the HTML file
            metadata: Dictionary with scheme_id, academic_year, source_url, source_title, etc.
            skip_duplicates: If True, skip chunks that already exist (based on content hash)
            
        Returns:
            Number of chunks added
        """
        if not self.is_available:
            raise RuntimeError("RAG store is unavailable.")
            
        title, headings, text = extract_html_structure(filepath)
        
        # Update metadata with extracted title and headings
        if title:
            metadata["source_title"] = title
        if headings:
            metadata["headings"] = str(headings)  # Store as string for ChromaDB compatibility
        
        chunks = chunk_text(text)
        chunks_added = 0
        scheme_id = metadata.get('scheme_id', 'doc')
        
        for j, chunk in enumerate(chunks):
            content_hash = compute_content_hash(chunk)
            
            # Check for duplicates if requested
            if skip_duplicates and self._chunk_exists(content_hash, scheme_id):
                logger.debug(f"Skipping duplicate chunk: {scheme_id}-html-chunk{j}")
                continue
            
            chunk_id = f"{scheme_id}-html-chunk{j}-{uuid.uuid4().hex[:6]}"
            
            chunk_meta = metadata.copy()
            chunk_meta["source_type"] = "html"
            chunk_meta["content_hash"] = content_hash
            
            self.collection.add(
                documents=[chunk],
                metadatas=[chunk_meta],
                ids=[chunk_id]
            )
            chunks_added += 1
            
        return chunks_added
        
    def delete_by_scheme(self, scheme_id: str):
        """Delete all chunks for a specific scheme_id."""
        if not self.is_available:
            return
        self.collection.delete(where={"scheme_id": scheme_id})

    def ingest_directory(self, directory: str, default_metadata: dict, skip_duplicates: bool = False) -> Dict[str, int]:
        """Ingest all supported documents from a directory.
        
        Args:
            directory: Path to directory containing PDF and HTML files
            default_metadata: Base metadata to apply to all documents (can be overridden per-file)
            skip_duplicates: If True, skip chunks that already exist
            
        Returns:
            Dictionary with counts: {"pdf": N, "html": N, "total": N, "skipped": N}
        """
        if not self.is_available:
            raise RuntimeError("RAG store is unavailable.")
            
        path = Path(directory)
        if not path.exists() or not path.is_dir():
            raise ValueError(f"Directory not found: {directory}")
        
        results = {"pdf": 0, "html": 0, "total": 0, "skipped": 0}
        
        for file_path in path.iterdir():
            if not file_path.is_file():
                continue
                
            ext = file_path.suffix.lower()
            file_metadata = default_metadata.copy()
            
            # Try to extract scheme_id from filename if not in default_metadata
            if 'scheme_id' not in file_metadata or not file_metadata['scheme_id']:
                # Use filename stem as scheme_id
                file_metadata['scheme_id'] = file_path.stem
            
            try:
                if ext == ".pdf":
                    added = self.ingest_pdf(str(file_path), file_metadata, skip_duplicates=skip_duplicates)
                    results["pdf"] += added
                    results["total"] += added
                elif ext in [".html", ".htm"]:
                    added = self.ingest_html(str(file_path), file_metadata, skip_duplicates=skip_duplicates)
                    results["html"] += added
                    results["total"] += added
                else:
                    results["skipped"] += 1
                    logger.warning(f"Skipping unsupported file: {file_path.name}")
            except Exception as e:
                logger.error(f"Failed to ingest {file_path.name}: {e}")
                results["skipped"] += 1
                
        return results

    def search_evidence(self, query: str, scheme_id: Optional[str] = None, academic_year: Optional[str] = None, n_results: int = 5) -> List[Dict[str, Any]]:
        """Search the vector store for evidence."""
        if not self.is_available or self.count() == 0:
            return []
            
        where_clause = {}
        if scheme_id:
            where_clause["scheme_id"] = scheme_id
        if academic_year:
            where_clause["academic_year"] = academic_year
            
        if len(where_clause) == 0:
            where = None
        elif len(where_clause) == 1:
            where = where_clause
        else:
            where = {"$and": [{k: v} for k, v in where_clause.items()]}
            
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where
            )
            
            evidence = []
            if results and results['documents'] and len(results['documents']) > 0:
                for i in range(len(results['documents'][0])):
                    evidence.append({
                        "content": results['documents'][0][i],
                        "metadata": results['metadatas'][0][i]
                    })
            return evidence
        except Exception as e:
            logger.error(f"Error during RAG search: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector store."""
        if not self.is_available:
            return {"available": False, "total_chunks": 0}
        
        try:
            # Get unique scheme_ids and academic_years
            all_data = self.collection.get()
            scheme_ids = set()
            academic_years = set()
            source_types = set()
            
            for meta in all_data.get('metadatas', []):
                if meta.get('scheme_id'):
                    scheme_ids.add(meta['scheme_id'])
                if meta.get('academic_year'):
                    academic_years.add(meta['academic_year'])
                if meta.get('source_type'):
                    source_types.add(meta['source_type'])
            
            return {
                "available": True,
                "total_chunks": self.count(),
                "unique_schemes": len(scheme_ids),
                "scheme_ids": sorted(list(scheme_ids)),
                "academic_years": sorted(list(academic_years)),
                "source_types": sorted(list(source_types))
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"available": True, "total_chunks": self.count(), "error": str(e)}
