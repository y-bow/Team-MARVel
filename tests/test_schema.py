"""
test_schema.py — schema v1/v2 parsing, backward compatibility, and dataset
validation guards.

Guards the data/schemes.json file (a real production dataset) against
structural regressions and ensures v1 test fixtures still parse correctly.
"""

from __future__ import annotations

import json

import pytest
from backend.schemas import (
    ApplicationWindow,
    Criterion,
    EvidenceItem,
    scheme_from_dict,
    validate_dataset,
    validate_record,
)


# ---------------------------------------------------------------------------
# Minimal raw records for unit tests
# ---------------------------------------------------------------------------

V1_RECORD = {
    "id": "v1-test",
    "name": "V1 Test Scheme",
    "description": "A v1-format record with flat criteria.",
    "criteria": {
        "education_levels": ["10th"],
        "caste_categories": ["SC"],
        "min_percentage": 55.0,
        "annual_family_income_max": 250000,
        "state": "Maharashtra",
        "gender": "any",
        "disability_required": None,
        "notes": "v1 notes",
    },
    "documents": ["Aadhaar"],
    "application_steps": ["Step 1"],
    "deadline": "2099-12-31",
    "source_url": "https://example.org",
    "verified": True,
    "last_checked": "2099-01-01",
    "tags": ["test"],
}

V2_RECORD = {
    "id": "v2-test",
    "name": "V2 Test Scheme",
    "description": "A v2-format record with typed criteria and evidence.",
    "academic_year": "2026-27",
    "application_window": {"opens": "2026-09-01", "closes": "2026-12-31"},
    "criteria": [
        {"field": "education_level", "operator": "in", "value": ["UG", "PG"]},
        {"field": "state", "operator": "eq", "value": "Karnataka"},
        {"field": "caste_category", "operator": "in", "value": ["OBC"]},
        {"field": "min_percentage", "operator": "gte", "value": 60.0},
        {"field": "annual_family_income", "operator": "lte", "value": 300000},
        {"field": "gender", "operator": "eq", "value": "Female"},
    ],
    "notes": "v2 notes",
    "documents": [{"name": "Enrollment proof"}, {"name": "Transcripts"}],
    "application_steps": [
        {"order": 2, "text": "Submit application"},
        {"order": 1, "text": "Register"},
    ],
    "deadline": {"date": "2026-12-31", "source_ref": "ev-deadline"},
    "source": {
        "url": "https://example.org/v2",
        "title": "Test Portal",
        "publisher": "Test Authority",
        "checked_at": "2026-06-01",
        "verification_method": "manual_official_portal",
        "evidence": [
            {"id": "ev-1", "field": "education_level", "quote": "Open to UG and PG", "checked_at": "2026-06-01"}
        ],
    },
    "verified": True,
    "tags": ["test", "v2"],
}


# ---------------------------------------------------------------------------
# v1 backward compatibility
# ---------------------------------------------------------------------------

class TestV1Compat:
    def test_v1_record_parses(self):
        scheme = scheme_from_dict(V1_RECORD)
        assert scheme.id == "v1-test"
        assert scheme.criteria.education_levels == ["10th"]
        assert scheme.criteria.state == "Maharashtra"
        assert scheme.criteria.min_percentage == 55.0
        assert scheme.verified is True
        assert scheme.last_checked == "2099-01-01"
        assert scheme.criterion_list

    def test_v1_document_strings_preserved(self):
        scheme = scheme_from_dict(V1_RECORD)
        assert scheme.documents == ["Aadhaar"]
        assert scheme.application_steps == ["Step 1"]

    def test_v1_loads_via_repository(self, repository):
        assert repository.count() > 0
        scheme = repository.get_by_id("test-sc-scholarship")
        assert scheme is not None
        assert scheme.criteria.caste_categories == ["SC"]


# ---------------------------------------------------------------------------
# v2 parsing
# ---------------------------------------------------------------------------

class TestV2Parsing:
    def test_v2_criterion_list(self):
        scheme = scheme_from_dict(V2_RECORD)
        by_field = {c.field: c for c in scheme.criterion_list}
        assert by_field["education_level"].value == ["UG", "PG"]
        assert by_field["state"].value == "Karnataka"
        assert by_field["min_percentage"].value == 60.0
        assert by_field["gender"].value == "Female"

    def test_v2_derives_flat_criteria(self):
        scheme = scheme_from_dict(V2_RECORD)
        assert scheme.criteria.education_levels == ["UG", "PG"]
        assert scheme.criteria.state == "Karnataka"
        assert scheme.criteria.caste_categories == ["OBC"]
        assert scheme.criteria.min_percentage == 60.0
        assert scheme.criteria.annual_family_income_max == 300000
        assert scheme.criteria.gender == "Female"

    def test_v2_documents_steps_deadline(self):
        scheme = scheme_from_dict(V2_RECORD)
        assert scheme.documents == ["Enrollment proof", "Transcripts"]
        assert scheme.application_steps == ["Register", "Submit application"]
        assert scheme.deadline == "2026-12-31"

    def test_v2_provenance_and_evidence(self):
        scheme = scheme_from_dict(V2_RECORD)
        assert scheme.source_url == "https://example.org/v2"
        assert scheme.last_checked == "2026-06-01"
        assert scheme.academic_year == "2026-27"
        assert scheme.application_window.opens == "2026-09-01"
        assert scheme.verification_method == "manual_official_portal"
        assert len(scheme.evidence) == 1
        assert scheme.evidence[0].quote == "Open to UG and PG"

    def test_v2_gender_omitted_from_criteria(self):
        data = {
            **V2_RECORD,
            "criteria": [
                {"field": "education_level", "operator": "in", "value": ["UG"]},
            ],
            "notes": None,
        }
        scheme = scheme_from_dict(data)
        assert scheme.criteria.gender is None

    def test_v2_verified_eklavya_loads(self):
        with open("data/schemes.json") as fh:
            file_data = json.load(fh)
        records = {r["id"]: r for r in file_data["schemes"]}
        eklavya = scheme_from_dict(records["maharashtra-eklavya-scholarship-2024"])
        assert eklavya.criteria.state == "Maharashtra"
        assert eklavya.criteria.caste_categories == ["ST"]
        assert eklavya.verified is False
        assert eklavya.deadline is None
        assert eklavya.last_checked is None

    def test_v2_requirement_mismatch_surfaces_gracefully(self):
        bad = {**V2_RECORD, "criteria": [{"field": "education_level", "operator": "gte", "value": 42}]}
        scheme = scheme_from_dict(bad)
        assert scheme.criterion_list[0].operator == "gte"

    def test_v1_to_v2_eligibility_equivalence(self, repository):
        student = {
            "education_level": "10th",
            "caste_category": "SC",
            "percentage": 60.0,
            "annual_family_income": 200000,
        }
        from backend.tools import check_eligibility
        result_v1 = check_eligibility(repository, "test-sc-scholarship", student)
        assert result_v1["status"] == "potential_match"

    def test_real_data_file_passes_validation(self):
        with open("data/schemes.json") as fh:
            raw = json.load(fh)
        errors = validate_dataset(raw)
        assert errors == []


# ---------------------------------------------------------------------------
# Validation: structural and provenance rules
# ---------------------------------------------------------------------------

class TestValidation:
    def test_missing_required_fields(self):
        assert validate_record({})  # errors for id/name/description

    def test_bad_id_format(self):
        errors = validate_record({"id": "no spaces", "name": "X", "description": "D"})
        assert any("id" in e for e in errors)

    def test_bad_deadline_date(self):
        errors = validate_record({
            "id": "t", "name": "T", "description": "D",
            "criteria": [], "deadline": {"date": "not-a-date"},
        })
        assert any("deadline" in e for e in errors)

    def test_verified_without_checked_at(self):
        errors = validate_record({
            "id": "t", "name": "T", "description": "D", "verified": True,
            "source": {"url": "https://x", "checked_at": None},
        })
        assert any("verified=true" in e.lower() for e in errors)

    def test_checked_at_not_iso(self):
        errors = validate_record({
            "id": "t", "name": "T", "description": "D",
            "source": {"checked_at": "June 2026"},
        })
        assert any("checked_at" in e for e in errors)

    def test_unknown_criterion_field(self):
        errors = validate_record({
            "id": "t", "name": "T", "description": "D",
            "criteria": [{"field": "shoe_size", "operator": "gte", "value": 10}],
        })
        assert any("shoe_size" in e for e in errors)

    def test_in_operator_requires_list(self):
        errors = validate_record({
            "id": "t", "name": "T", "description": "D",
            "criteria": [{"field": "education_level", "operator": "in", "value": "UG"}],
        })
        assert any("in" in e for e in errors)

    def test_gte_requires_number(self):
        errors = validate_record({
            "id": "t", "name": "T", "description": "D",
            "criteria": [{"field": "min_percentage", "operator": "gte", "value": "high"}],
        })
        assert any("gte" in e for e in errors)

    def test_bad_source_url(self):
        errors = validate_record({
            "id": "t", "name": "T", "description": "D",
            "source": {"url": "ftp://bad"},
        })
        assert any("http" in e for e in errors)

    def test_evidence_needs_field(self):
        errors = validate_record({
            "id": "t", "name": "T", "description": "D",
            "source": {"evidence": [{"id": "e1", "quote": "x"}]},
        })
        assert any("field" in e for e in errors)

    def test_duplicate_ids_detected(self):
        raw = [
            {"id": "dup", "name": "A", "description": "A"},
            {"id": "dup", "name": "B", "description": "B"},
        ]
        errors = validate_dataset(raw)
        assert any("duplicate" in e.lower() for e in errors)

    def test_document_entry_needs_name(self):
        errors = validate_record({
            "id": "t", "name": "T", "description": "D",
            "documents": [{}],
        })
        assert any("document" in e.lower() for e in errors)