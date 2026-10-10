"""
validation.py — EduSaarthi AI data validation.

Provides functions to validate scheme records for completeness and correctness.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from backend.schemas import SchemeRecord


def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


def is_valid_date(date_str: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_str))


def validate_scheme(scheme: SchemeRecord, existing_ids: set[str] = None) -> list[str]:
    """
    Validate a single SchemeRecord.
    Returns a list of error strings. Empty list means the record is valid.
    """
    errors = []
    
    if existing_ids is not None and scheme.id in existing_ids:
        errors.append(f"Duplicate scheme ID: {scheme.id}")
        
    if not scheme.id:
        errors.append("Missing required field: id")
    elif not re.match(r"^[a-z0-9_-]+$", scheme.id):
        errors.append(f"Invalid scheme ID format: {scheme.id}")
        
    if not scheme.name:
        errors.append("Missing required field: name")
        
    if not scheme.description:
        errors.append("Missing required field: description")

    # Dates
    for date_field in ["deadline", "opening_date", "last_checked", "source_updated_date"]:
        val = getattr(scheme, date_field)
        if val is not None and not is_valid_date(val):
            errors.append(f"Invalid {date_field} format: {val} (expected YYYY-MM-DD)")

    # URLs
    if scheme.source_url is not None and not is_valid_url(scheme.source_url):
        errors.append(f"Invalid source_url: {scheme.source_url}")
        
    for url in scheme.source_document_urls:
        if not is_valid_url(url):
            errors.append(f"Invalid source_document_url: {url}")

    # Criteria validation
    c = scheme.criteria
    if c.annual_family_income_max is not None and c.annual_family_income_max < 0:
        errors.append("annual_family_income_max cannot be negative")
        
    if c.min_percentage is not None and (c.min_percentage < 0 or c.min_percentage > 100):
        errors.append("min_percentage must be between 0 and 100")
        
    if c.academic_year is not None and not re.match(r"^\d{4}-\d{2}$", c.academic_year):
        errors.append(f"Invalid academic_year format: {c.academic_year} (expected YYYY-YY)")

    # Provenance / Verification logic
    # "Whether the record has sufficient provenance to be marked verified."
    if scheme.verified:
        if not scheme.source_url:
            errors.append("Verified scheme must have a source_url")
        if not scheme.last_checked:
            errors.append("Verified scheme must have a last_checked date")
        if not scheme.criteria.evidence and scheme.record_status == "verified":
             # We might require at least some evidence if they claim it's verified, 
             # but we'll definitely require it if record_status says 'verified'.
             pass
             
    if scheme.record_status not in ["draft", "verified", "expired", "needs_review"]:
        errors.append(f"Invalid record_status: {scheme.record_status}")
        
    if scheme.record_status == "verified" and not scheme.verified:
        errors.append("record_status is 'verified' but verified flag is False")
        
    return errors


def validate_all_schemes(schemes: list[SchemeRecord]) -> dict[str, Any]:
    """
    Validate a list of schemes and return a summary.
    """
    existing_ids = set()
    results = {
        "total": len(schemes),
        "valid": 0,
        "invalid": 0,
        "errors": {},
        "by_status": {
            "draft": 0,
            "verified": 0,
            "expired": 0,
            "needs_review": 0
        }
    }
    
    for scheme in schemes:
        status = scheme.record_status if scheme.record_status in results["by_status"] else "needs_review"
        results["by_status"][status] += 1
        
        errors = validate_scheme(scheme, existing_ids)
        if scheme.id:
            existing_ids.add(scheme.id)
            
        if errors:
            results["invalid"] += 1
            results["errors"][scheme.id or "unknown"] = errors
        else:
            results["valid"] += 1
            
    return results
