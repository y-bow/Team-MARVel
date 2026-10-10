"""
test_validation.py — Unit tests for the data validation module.
"""

from backend.schemas import SchemeRecord, EligibilityCriteria, scheme_from_dict
from backend.validation import validate_scheme, validate_all_schemes, is_valid_url, is_valid_date

def get_valid_scheme():
    return SchemeRecord(
        id="test-valid-scheme",
        name="Valid Scheme Name",
        description="A perfectly valid test scheme.",
        criteria=EligibilityCriteria(
            annual_family_income_max=250000,
            min_percentage=60.0,
            evidence={"annual_family_income_max": "Section 2.1"}
        ),
        deadline="2024-12-31",
        source_url="https://example.gov.in/scheme",
        verified=True,
        last_checked="2024-10-01",
        record_status="verified"
    )

def test_is_valid_url():
    assert is_valid_url("https://example.com")
    assert is_valid_url("http://example.com/path?q=1")
    assert not is_valid_url("not-a-url")
    assert not is_valid_url("")

def test_is_valid_date():
    assert is_valid_date("2024-12-31")
    assert not is_valid_date("2024/12/31")
    assert not is_valid_date("31-12-2024")
    assert not is_valid_date("invalid")
    
def test_valid_scheme():
    scheme = get_valid_scheme()
    errors = validate_scheme(scheme)
    assert not errors

def test_missing_required_fields():
    scheme = get_valid_scheme()
    scheme.id = ""
    errors = validate_scheme(scheme)
    assert "Missing required field: id" in errors
    
    scheme.id = "invalid id!"
    errors = validate_scheme(scheme)
    assert any("Invalid scheme ID format" in e for e in errors)

def test_invalid_dates():
    scheme = get_valid_scheme()
    scheme.deadline = "31-12-2024"
    errors = validate_scheme(scheme)
    assert any("Invalid deadline format" in e for e in errors)

def test_invalid_urls():
    scheme = get_valid_scheme()
    scheme.source_url = "www.example.com"
    errors = validate_scheme(scheme)
    assert any("Invalid source_url" in e for e in errors)

def test_invalid_criteria():
    scheme = get_valid_scheme()
    scheme.criteria.annual_family_income_max = -100
    scheme.criteria.min_percentage = 110
    errors = validate_scheme(scheme)
    assert any("annual_family_income_max cannot be negative" in e for e in errors)
    assert any("min_percentage must be between 0 and 100" in e for e in errors)

def test_verification_provenance():
    scheme = get_valid_scheme()
    scheme.verified = True
    scheme.source_url = None
    errors = validate_scheme(scheme)
    assert any("Verified scheme must have a source_url" in e for e in errors)
    
    scheme.source_url = "https://example.com"
    scheme.last_checked = None
    errors = validate_scheme(scheme)
    assert any("Verified scheme must have a last_checked date" in e for e in errors)

def test_record_status():
    scheme = get_valid_scheme()
    scheme.record_status = "verified"
    scheme.verified = False
    errors = validate_scheme(scheme)
    assert any("record_status is 'verified' but verified flag is False" in e for e in errors)

def test_duplicate_ids():
    scheme1 = get_valid_scheme()
    scheme2 = get_valid_scheme()
    results = validate_all_schemes([scheme1, scheme2])
    assert results["invalid"] == 1
    assert any("Duplicate scheme ID" in e for e in results["errors"]["test-valid-scheme"])

def test_validate_all_summary():
    scheme1 = get_valid_scheme()
    scheme2 = get_valid_scheme()
    scheme2.id = "scheme-2"
    scheme2.verified = False
    scheme2.record_status = "draft"
    
    results = validate_all_schemes([scheme1, scheme2])
    assert results["total"] == 2
    assert results["valid"] == 2
    assert results["by_status"]["verified"] == 1
    assert results["by_status"]["draft"] == 1
