"""
test_eligibility.py — unit tests for the deterministic eligibility engine.

These tests verify the new eligibility engine (backend/eligibility.py) behavior
including edge cases, optional vs mandatory criteria, and mixed outcomes.
"""

import pytest
from backend.eligibility import (
    evaluate_eligibility,
    evaluate_eligibility_for_tool,
    CriterionState,
    OverallOutcome,
)
from backend.schemas import SchemeRecord, scheme_from_dict


# =============================================================================
# Synthetic scheme fixtures for testing
# =============================================================================

def make_scheme(**overrides) -> SchemeRecord:
    """Create a SchemeRecord with sensible defaults, override as needed."""
    base = {
        "id": "test-scheme",
        "name": "Test Scheme",
        "description": "A test scholarship.",
        "criteria": {
            "education_levels": ["10th", "12th"],
            "state": None,
            "caste_categories": ["SC", "ST"],
            "min_percentage": 60.0,
            "annual_family_income_max": 250000.0,
            "gender": "any",
            "disability_required": None,
            "notes": None,  # Default to None to avoid triggering NEEDS_REVIEW
        },
        "documents": ["Aadhaar", "Marksheet"],
        "application_steps": ["Step 1", "Step 2"],
        "deadline": "2025-12-31",
        "source_url": "https://example.gov.in/test",
        "verified": True,
        "last_checked": "2025-01-01",
        "tags": ["test"],
    }
    base.update(overrides)
    # Rebuild criteria if criteria dict was overridden
    if "criteria" in overrides:
        base["criteria"] = {**base["criteria"], **overrides["criteria"]}
    return scheme_from_dict(base)


# =============================================================================
# 1. All mandatory criteria met
# =============================================================================

def test_all_mandatory_criteria_met_returns_eligible():
    """When all mandatory criteria are satisfied, outcome should be ELIGIBLE."""
    scheme = make_scheme()
    student = {
        "education_level": "10th",
        "state": "Maharashtra",
        "caste_category": "SC",
        "percentage": 75.0,
        "annual_family_income": 200000,
        "gender": "Female",
        "disability": False,
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    # All criteria should be MET
    for c in result.criteria:
        assert c.state == CriterionState.MET, f"Criterion {c.criterion} not met: {c.explanation}"


# =============================================================================
# 2. Family income above the limit
# =============================================================================

def test_income_above_limit_returns_ineligible():
    """Income exceeding the scheme limit should make student INELIGIBLE."""
    scheme = make_scheme()
    student = {
        "education_level": "10th",
        "caste_category": "SC",
        "percentage": 75.0,
        "annual_family_income": 300000,  # Above 250000 limit
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.INELIGIBLE
    income_eval = next(c for c in result.criteria if c.criterion == "annual_family_income")
    assert income_eval.state == CriterionState.NOT_MET
    assert "exceeds" in income_eval.explanation


# =============================================================================
# 3. Income exactly equal to the limit
# =============================================================================

def test_income_exactly_at_limit_returns_eligible():
    """Income exactly at the limit should be considered MET (<= comparison)."""
    scheme = make_scheme()
    student = {
        "education_level": "10th",
        "caste_category": "SC",
        "percentage": 75.0,
        "annual_family_income": 250000,  # Exactly at limit
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    income_eval = next(c for c in result.criteria if c.criterion == "annual_family_income")
    assert income_eval.state == CriterionState.MET


# =============================================================================
# 4. Marks below, equal to and above the threshold
# =============================================================================

def test_percentage_below_threshold_returns_ineligible():
    scheme = make_scheme()
    student = {
        "education_level": "10th",
        "caste_category": "SC",
        "percentage": 50.0,  # Below 60%
        "annual_family_income": 200000,
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.INELIGIBLE
    pct_eval = next(c for c in result.criteria if c.criterion == "percentage")
    assert pct_eval.state == CriterionState.NOT_MET
    assert "below" in pct_eval.explanation


def test_percentage_equal_to_threshold_returns_eligible():
    """Percentage exactly at threshold should be MET (>= comparison)."""
    scheme = make_scheme()
    student = {
        "education_level": "10th",
        "caste_category": "SC",
        "percentage": 60.0,  # Exactly at threshold
        "annual_family_income": 200000,
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    pct_eval = next(c for c in result.criteria if c.criterion == "percentage")
    assert pct_eval.state == CriterionState.MET


def test_percentage_above_threshold_returns_eligible():
    scheme = make_scheme()
    student = {
        "education_level": "10th",
        "caste_category": "SC",
        "percentage": 80.0,
        "annual_family_income": 200000,
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    pct_eval = next(c for c in result.criteria if c.criterion == "percentage")
    assert pct_eval.state == CriterionState.MET


# =============================================================================
# 5. Missing income or marks
# =============================================================================

def test_missing_income_returns_needs_information():
    """Missing income data should result in NEEDS_INFORMATION."""
    scheme = make_scheme()
    student = {
        "education_level": "10th",
        "caste_category": "SC",
        "percentage": 75.0,
        # income missing
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.NEEDS_INFORMATION
    income_eval = next(c for c in result.criteria if c.criterion == "annual_family_income")
    assert income_eval.state == CriterionState.UNKNOWN
    assert income_eval.missing_info_reason is not None


def test_missing_percentage_returns_needs_information():
    scheme = make_scheme()
    student = {
        "education_level": "10th",
        "caste_category": "SC",
        "annual_family_income": 200000,
        # percentage missing
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.NEEDS_INFORMATION
    pct_eval = next(c for c in result.criteria if c.criterion == "percentage")
    assert pct_eval.state == CriterionState.UNKNOWN


# =============================================================================
# 6. Incorrect domicile or course (education_level)
# =============================================================================

def test_incorrect_state_returns_ineligible():
    """Wrong state for state-specific scheme should be INELIGIBLE."""
    scheme = make_scheme(criteria={"state": "Maharashtra"})
    student = {
        "education_level": "10th",
        "state": "Karnataka",  # Wrong state
        "caste_category": "SC",
        "percentage": 75.0,
        "annual_family_income": 200000,
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.INELIGIBLE
    state_eval = next(c for c in result.criteria if c.criterion == "state")
    assert state_eval.state == CriterionState.NOT_MET


def test_incorrect_education_level_returns_ineligible():
    """Wrong education level should be INELIGIBLE."""
    scheme = make_scheme()
    student = {
        "education_level": "UG",  # Scheme only accepts 10th, 12th
        "caste_category": "SC",
        "percentage": 75.0,
        "annual_family_income": 200000,
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.INELIGIBLE
    edu_eval = next(c for c in result.criteria if c.criterion == "education_level")
    assert edu_eval.state == CriterionState.NOT_MET


# =============================================================================
# 7. Category requirements when category is unknown
# =============================================================================

def test_missing_caste_category_returns_needs_information():
    """Missing caste category for restricted scheme should be NEEDS_INFORMATION."""
    scheme = make_scheme()
    student = {
        "education_level": "10th",
        "percentage": 75.0,
        "annual_family_income": 200000,
        # caste_category missing
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.NEEDS_INFORMATION
    caste_eval = next(c for c in result.criteria if c.criterion == "caste_category")
    assert caste_eval.state == CriterionState.UNKNOWN


def test_wrong_caste_category_returns_ineligible():
    """Non-matching caste category should be INELIGIBLE."""
    scheme = make_scheme()
    student = {
        "education_level": "10th",
        "caste_category": "General",  # Scheme only SC, ST
        "percentage": 75.0,
        "annual_family_income": 200000,
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.INELIGIBLE
    caste_eval = next(c for c in result.criteria if c.criterion == "caste_category")
    assert caste_eval.state == CriterionState.NOT_MET


# =============================================================================
# 8. Optional versus mandatory criteria
# =============================================================================

def test_optional_criteria_not_required_for_eligible():
    """Criteria not specified by scheme should not affect eligibility."""
    # Scheme with NO income restriction, NO percentage restriction
    scheme = make_scheme(criteria={
        "education_levels": ["10th"],
        "state": None,
        "caste_categories": ["SC"],
        "min_percentage": None,          # No percentage requirement
        "annual_family_income_max": None,  # No income requirement
        "gender": "any",
        "disability_required": None,
    })
    student = {
        "education_level": "10th",
        "caste_category": "SC",
        # No percentage, no income provided
    }
    result = evaluate_eligibility(scheme, student)
    # Should be ELIGIBLE because only education_level and caste_category are mandatory
    assert result.outcome == OverallOutcome.ELIGIBLE
    # Verify those criteria don't appear in results (they're not specified)
    criterion_names = [c.criterion for c in result.criteria]
    assert "percentage" not in criterion_names
    assert "annual_family_income" not in criterion_names


def test_gender_any_not_mandatory():
    """Gender='any' should not appear as a mandatory criterion."""
    scheme = make_scheme(criteria={"gender": "any"})
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000}
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    criterion_names = [c.criterion for c in result.criteria]
    assert "gender" not in criterion_names


def test_disability_not_specified_not_mandatory():
    """disability_required=None should not appear as a criterion."""
    scheme = make_scheme(criteria={"disability_required": None})
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000}
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    criterion_names = [c.criterion for c in result.criteria]
    assert "disability" not in criterion_names


# =============================================================================
# 9. Missing or unverified rule evidence
# =============================================================================

def test_scheme_without_source_url_marks_evidence_as_knowledge_base():
    """Scheme without source_url should reference knowledge_base as evidence."""
    scheme = make_scheme(source_url=None)
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000}
    result = evaluate_eligibility(scheme, student)
    for c in result.criteria:
        assert c.evidence_reference == "knowledge_base"


def test_unverified_scheme_with_notes_returns_needs_review():
    """Free-form notes that can't be evaluated should trigger NEEDS_REVIEW."""
    scheme = make_scheme(criteria={"notes": "Must have recommendation letter from principal"})
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000}
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.NEEDS_REVIEW
    notes_eval = next(c for c in result.criteria if c.criterion == "notes")
    assert notes_eval.unsupported_condition is not None


# =============================================================================
# 10. Contradictory or unsupported criteria
# =============================================================================

def test_contradictory_criteria_marked_needs_review():
    """Scheme with contradictory notes should be flagged for review."""
    scheme = make_scheme(criteria={
        "notes": "Must be SC category. Must be General category."  # Contradiction
    })
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000}
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.NEEDS_REVIEW
    notes_eval = next(c for c in result.criteria if c.criterion == "notes")
    assert notes_eval.unsupported_condition is not None


# =============================================================================
# 11. Multiple criteria with mixed outcomes
# =============================================================================

def test_mixed_met_and_unknown_returns_needs_information():
    """Some criteria met, some unknown -> NEEDS_INFORMATION (no failures)."""
    scheme = make_scheme()
    student = {
        "education_level": "10th",      # MET
        "caste_category": "SC",         # MET
        "percentage": 75.0,             # MET
        # income missing -> UNKNOWN
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.NEEDS_INFORMATION
    states = {c.criterion: c.state for c in result.criteria}
    assert states["education_level"] == CriterionState.MET
    assert states["caste_category"] == CriterionState.MET
    assert states["percentage"] == CriterionState.MET
    assert states["annual_family_income"] == CriterionState.UNKNOWN


def test_mixed_met_and_not_met_returns_ineligible():
    """One criterion not met -> INELIGIBLE regardless of others."""
    scheme = make_scheme()
    student = {
        "education_level": "10th",      # MET
        "caste_category": "SC",         # MET
        "percentage": 75.0,             # MET
        "annual_family_income": 300000, # NOT_MET (above limit)
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.INELIGIBLE


def test_mixed_unknown_and_not_met_returns_ineligible():
    """NOT_MET takes precedence over UNKNOWN -> INELIGIBLE."""
    scheme = make_scheme()
    student = {
        "education_level": "10th",      # MET
        "caste_category": "General",    # NOT_MET (wrong caste)
        "percentage": 75.0,             # MET
        # income missing -> UNKNOWN
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.INELIGIBLE


# =============================================================================
# 12. Student profile changes between requests
# =============================================================================

def test_student_profile_update_changes_result():
    """Updated profile should produce different eligibility result."""
    scheme = make_scheme()
    
    # First request: missing income
    student_v1 = {
        "education_level": "10th",
        "caste_category": "SC",
        "percentage": 75.0,
    }
    result_v1 = evaluate_eligibility(scheme, student_v1)
    assert result_v1.outcome == OverallOutcome.NEEDS_INFORMATION
    
    # Second request: income provided and within limit
    student_v2 = {
        "education_level": "10th",
        "caste_category": "SC",
        "percentage": 75.0,
        "annual_family_income": 200000,
    }
    result_v2 = evaluate_eligibility(scheme, student_v2)
    assert result_v2.outcome == OverallOutcome.ELIGIBLE
    
    # Third request: income provided but exceeds limit
    student_v3 = {
        "education_level": "10th",
        "caste_category": "SC",
        "percentage": 75.0,
        "annual_family_income": 300000,
    }
    result_v3 = evaluate_eligibility(scheme, student_v3)
    assert result_v3.outcome == OverallOutcome.INELIGIBLE


def test_disability_requirement_change():
    """Changing disability_required from None to True changes criteria."""
    # Scheme without disability requirement
    scheme_no_dis = make_scheme(criteria={"disability_required": None})
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000, "disability": False}
    result_no_dis = evaluate_eligibility(scheme_no_dis, student)
    assert result_no_dis.outcome == OverallOutcome.ELIGIBLE
    criterion_names = [c.criterion for c in result_no_dis.criteria]
    assert "disability" not in criterion_names
    
    # Same scheme but with disability required
    scheme_dis = make_scheme(criteria={"disability_required": True})
    result_dis = evaluate_eligibility(scheme_dis, student)
    assert result_dis.outcome == OverallOutcome.INELIGIBLE
    dis_eval = next(c for c in result_dis.criteria if c.criterion == "disability")
    assert dis_eval.state == CriterionState.NOT_MET


# =============================================================================
# 13. Regression tests for existing tools and endpoints
# =============================================================================

def test_evaluate_eligibility_for_tool_returns_legacy_format():
    """Adapter function should return format compatible with check_eligibility tool."""
    scheme = make_scheme()
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000}
    
    result = evaluate_eligibility_for_tool(scheme, student)
    
    # Legacy fields
    assert "scheme_id" in result
    assert "scheme_name" in result
    assert "status" in result
    assert "satisfied_criteria" in result
    assert "unsatisfied_criteria" in result
    assert "unknown_criteria" in result
    assert "additional_notes" in result
    assert "disclaimer" in result
    
    # New structured fields
    assert "outcome" in result
    assert "criteria_details" in result
    
    # Status mapping
    assert result["status"] == "potential_match"  # ELIGIBLE -> potential_match
    assert result["outcome"] == "eligible"


def test_evaluate_eligibility_for_tool_ineligible_maps_correctly():
    """INELIGIBLE should map to not_eligible_based_on_provided_information."""
    scheme = make_scheme()
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 300000}
    
    result = evaluate_eligibility_for_tool(scheme, student)
    assert result["status"] == "not_eligible_based_on_provided_information"
    assert result["outcome"] == "ineligible"


def test_evaluate_eligibility_for_tool_needs_info_maps_correctly():
    """NEEDS_INFORMATION should map to more_information_needed."""
    scheme = make_scheme()
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0}
    
    result = evaluate_eligibility_for_tool(scheme, student)
    assert result["status"] == "more_information_needed"
    assert result["outcome"] == "needs_information"


def test_evaluate_eligibility_for_tool_needs_review_maps_to_needs_info():
    """NEEDS_REVIEW should map to more_information_needed (safe fallback)."""
    scheme = make_scheme(criteria={"notes": "Requires principal recommendation"})
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000}
    
    result = evaluate_eligibility_for_tool(scheme, student)
    assert result["status"] == "more_information_needed"
    assert result["outcome"] == "needs_review"


def test_state_all_india_not_restrictive():
    """All-India scheme (state=None) should not require state match."""
    scheme = make_scheme(criteria={"state": None})
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000}
    # No state provided - should still be eligible
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    # State criterion should not appear
    criterion_names = [c.criterion for c in result.criteria]
    assert "state" not in criterion_names


def test_caste_any_not_restrictive():
    """caste_categories=['any'] should not restrict."""
    scheme = make_scheme(criteria={"caste_categories": ["any"]})
    student = {"education_level": "10th", "caste_category": "General", "percentage": 75.0, "annual_family_income": 200000}
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    criterion_names = [c.criterion for c in result.criteria]
    assert "caste_category" not in criterion_names


def test_education_levels_any_not_restrictive():
    """education_levels=['any'] should not restrict."""
    scheme = make_scheme(criteria={"education_levels": ["any"]})
    student = {"education_level": "PhD", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000}
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    criterion_names = [c.criterion for c in result.criteria]
    assert "education_level" not in criterion_names


# =============================================================================
# Additional edge cases
# =============================================================================

def test_invalid_percentage_value_treated_as_unknown():
    """Non-numeric percentage should be UNKNOWN, not crash."""
    scheme = make_scheme()
    student = {"education_level": "10th", "caste_category": "SC", "percentage": "invalid", "annual_family_income": 200000}
    result = evaluate_eligibility(scheme, student)
    pct_eval = next(c for c in result.criteria if c.criterion == "percentage")
    assert pct_eval.state == CriterionState.UNKNOWN


def test_invalid_income_value_treated_as_unknown():
    """Non-numeric income should be UNKNOWN, not crash."""
    scheme = make_scheme()
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": "high"}
    result = evaluate_eligibility(scheme, student)
    inc_eval = next(c for c in result.criteria if c.criterion == "annual_family_income")
    assert inc_eval.state == CriterionState.UNKNOWN


def test_case_insensitive_matching():
    """String comparisons should be case-insensitive."""
    scheme = make_scheme()
    student = {
        "education_level": "10TH",  # Uppercase
        "caste_category": "sc",      # Lowercase
        "percentage": 75.0,
        "annual_family_income": 200000,
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE


def test_whitespace_handling():
    """Whitespace in student values should be stripped."""
    scheme = make_scheme()
    student = {
        "education_level": " 10th ",   # Extra spaces
        "caste_category": " SC ",      # Extra spaces
        "percentage": 75.0,
        "annual_family_income": 200000,
    }
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE


def test_empty_string_treated_as_missing():
    """Empty string should be treated as missing (None)."""
    scheme = make_scheme()
    student = {
        "education_level": "",
        "caste_category": "SC",
        "percentage": 75.0,
        "annual_family_income": 200000,
    }
    result = evaluate_eligibility(scheme, student)
    edu_eval = next(c for c in result.criteria if c.criterion == "education_level")
    assert edu_eval.state == CriterionState.UNKNOWN


def test_disability_true_required_student_has_it():
    """disability_required=True with student disability=True -> MET."""
    scheme = make_scheme(criteria={"disability_required": True})
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000, "disability": True}
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    dis_eval = next(c for c in result.criteria if c.criterion == "disability")
    assert dis_eval.state == CriterionState.MET


def test_disability_false_not_required_always_met():
    """disability_required=False should always be MET."""
    scheme = make_scheme(criteria={"disability_required": False})
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000, "disability": False}
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    dis_eval = next(c for c in result.criteria if c.criterion == "disability")
    assert dis_eval.state == CriterionState.MET


def test_scheme_with_no_restrictions_all_eligible():
    """Scheme with all criteria unrestricted should always be ELIGIBLE."""
    scheme = make_scheme(criteria={
        "education_levels": ["any"],
        "state": None,
        "caste_categories": ["any"],
        "min_percentage": None,
        "annual_family_income_max": None,
        "gender": "any",
        "disability_required": None,
        "notes": None,  # Explicitly no notes
    })
    student = {}  # Empty profile
    result = evaluate_eligibility(scheme, student)
    assert result.outcome == OverallOutcome.ELIGIBLE
    # No criteria should be evaluated (all unrestricted, no notes)
    assert len(result.criteria) == 0


def test_disclaimer_always_present():
    """Disclaimer should always be included in result."""
    scheme = make_scheme()
    student = {"education_level": "10th", "caste_category": "SC", "percentage": 75.0, "annual_family_income": 200000}
    result = evaluate_eligibility(scheme, student)
    assert result.disclaimer is not None
    assert len(result.disclaimer) > 50
    assert "official" in result.disclaimer.lower()
    assert "verify" in result.disclaimer.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])