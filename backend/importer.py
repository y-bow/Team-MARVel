"""
importer.py — EduSaarthi AI scholarship data ingestion and validation tool.

Usage:
    python -m backend.importer validate <path_to_json>
"""

import argparse
import json
import sys
from pathlib import Path

from backend.schemas import scheme_from_dict
from backend.validation import validate_all_schemes


def load_and_validate(filepath: str) -> bool:
    """
    Load a JSON file, parse schemes, and validate them.
    Prints a summary of the validation.
    Returns True if all records are valid, False otherwise.
    """
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File '{filepath}' not found.")
        return False
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in '{filepath}': {e}")
        return False
        
    if not isinstance(data, list):
        print("Error: JSON root must be a list of scheme objects.")
        return False
        
    schemes = []
    parse_errors = []
    
    for i, item in enumerate(data):
        try:
            schemes.append(scheme_from_dict(item))
        except ValueError as e:
            parse_errors.append(f"Record {i}: {e}")
            
    if parse_errors:
        print(f"Failed to parse {len(parse_errors)} records:")
        for err in parse_errors:
            print(f" - {err}")
        print("\nAborting validation due to parse errors.")
        return False
        
    results = validate_all_schemes(schemes)
    
    print(f"=== Validation Summary for {filepath} ===")
    print(f"Total records : {results['total']}")
    print(f"Valid records : {results['valid']}")
    print(f"Invalid       : {results['invalid']}")
    print("\nStatus breakdown:")
    for status, count in results['by_status'].items():
        print(f" - {status}: {count}")
        
    if results['invalid'] > 0:
        print("\n=== Validation Errors ===")
        for scheme_id, errors in results['errors'].items():
            print(f"\nScheme: {scheme_id}")
            for err in errors:
                print(f"  - {err}")
        return False
        
    print("\nAll records are valid!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EduSaarthi AI Data Importer/Validator")
    parser.add_argument("action", choices=["validate"], help="Action to perform")
    parser.add_argument("file", help="Path to the JSON file to validate")
    
    args = parser.parse_args()
    
    if args.action == "validate":
        success = load_and_validate(args.file)
        sys.exit(0 if success else 1)
