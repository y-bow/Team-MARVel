"""
ingest_rag.py — Ingestion script for official scholarship guidelines into RAG.

Usage:
    # Single file
    python -m backend.ingest_rag <path_to_pdf_or_html> --scheme_id <id> --academic_year <year> --source_url <url> --source_title <title>

    # Batch directory ingestion
    python -m backend.ingest_rag --directory <path_to_dir> --scheme_id <id> --academic_year <year>

    # Show stats
    python -m backend.ingest_rag --stats
"""

import argparse
import sys
from pathlib import Path

from backend.config import load_config
from backend.rag import RAGStore


def main():
    parser = argparse.ArgumentParser(description="Ingest documents into the RAG vector store.")
    
    # Input modes: single file OR directory
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("file", nargs="?", help="Path to PDF or HTML file")
    input_group.add_argument("--directory", help="Path to directory containing PDF/HTML files")
    input_group.add_argument("--stats", action="store_true", help="Show vector store statistics")
    
    # Metadata arguments
    parser.add_argument("--scheme_id", help="Scheme ID this document belongs to (required for single file)")
    parser.add_argument("--academic_year", default="", help="Academic year (e.g. 2024-25)")
    parser.add_argument("--source_url", default="", help="Official URL for this document")
    parser.add_argument("--source_title", default="", help="Title of the source")
    parser.add_argument("--clear_existing", action="store_true", help="Clear existing chunks for this scheme_id before ingestion")
    parser.add_argument("--skip_duplicates", action="store_true", help="Skip chunks that already exist (based on content hash)")
    
    args = parser.parse_args()
    
    cfg = load_config(require_api_key=False)
    rag = RAGStore(persist_directory=cfg.vector_store_path, embedding_model_name=cfg.embedding_model)
    
    if not rag.is_available:
        print("Error: RAG store is unavailable.")
        sys.exit(1)
    
    # Stats mode
    if args.stats:
        stats = rag.get_stats()
        print(f"RAG Store Statistics:")
        print(f"  Available: {stats.get('available', False)}")
        print(f"  Total chunks: {stats.get('total_chunks', 0)}")
        print(f"  Unique schemes: {stats.get('unique_schemes', 0)}")
        if stats.get('scheme_ids'):
            print(f"  Scheme IDs: {', '.join(stats['scheme_ids'])}")
        if stats.get('academic_years'):
            print(f"  Academic years: {', '.join(stats['academic_years'])}")
        if stats.get('source_types'):
            print(f"  Source types: {', '.join(stats['source_types'])}")
        if stats.get('error'):
            print(f"  Error: {stats['error']}")
        return
    
    # Directory batch ingestion mode
    if args.directory:
        dir_path = Path(args.directory)
        if not dir_path.exists() or not dir_path.is_dir():
            print(f"Error: Directory '{args.directory}' not found.")
            sys.exit(1)
            
        if not args.scheme_id:
            print("Warning: No scheme_id provided. Will use filename as scheme_id for each file.")
        
        metadata = {
            "scheme_id": args.scheme_id or "",
            "academic_year": args.academic_year,
            "source_url": args.source_url,
            "source_title": args.source_title
        }
        
        if args.clear_existing and args.scheme_id:
            print(f"Clearing existing chunks for scheme '{args.scheme_id}'...")
            rag.delete_by_scheme(args.scheme_id)
        
        print(f"Ingesting directory '{args.directory}'...")
        try:
            results = rag.ingest_directory(str(dir_path), metadata, skip_duplicates=args.skip_duplicates)
            print(f"Results:")
            print(f"  PDF files: {results['pdf']} chunks")
            print(f"  HTML files: {results['html']} chunks")
            print(f"  Total chunks added: {results['total']}")
            print(f"  Skipped/errors: {results['skipped']}")
            print(f"  Total chunks in store: {rag.count()}")
        except Exception as e:
            print(f"Error during ingestion: {e}")
            sys.exit(1)
        return
    
    # Single file mode
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File '{args.file}' not found.")
        sys.exit(1)
        
    if not args.scheme_id:
        print("Error: --scheme_id is required for single file ingestion.")
        sys.exit(1)
        
    if args.clear_existing:
        print(f"Clearing existing chunks for scheme '{args.scheme_id}'...")
        rag.delete_by_scheme(args.scheme_id)
        
    metadata = {
        "scheme_id": args.scheme_id,
        "academic_year": args.academic_year,
        "source_url": args.source_url,
        "source_title": args.source_title
    }
    
    print(f"Ingesting '{args.file}'...")
    chunks_added = 0
    ext = file_path.suffix.lower()
    
    try:
        if ext == ".pdf":
            chunks_added = rag.ingest_pdf(str(file_path), metadata, skip_duplicates=args.skip_duplicates)
        elif ext in [".html", ".htm"]:
            chunks_added = rag.ingest_html(str(file_path), metadata, skip_duplicates=args.skip_duplicates)
        else:
            print(f"Error: Unsupported file extension '{ext}'. Use .pdf or .html")
            sys.exit(1)
    except Exception as e:
        print(f"Error during ingestion: {e}")
        sys.exit(1)
        
    print(f"Successfully added {chunks_added} chunks to RAG store.")
    print(f"Total chunks in store: {rag.count()}")


if __name__ == "__main__":
    main()