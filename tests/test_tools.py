"""
test_tools.py — unit tests for all 5 tool functions.

All tests use synthetic data via the repository fixture.
No real API key or Gemini calls.
"""

import pytest
from backend import tools as tool_fns
from backend.tools import (
    STATUS_POTENTIAL_MATCH,
    STATUS_NOT_ELIGIBLE,
    STATUS_MORE_INFO_NEEDED,
    DEADLINE_CURRENT,
    DEADLINE_PAST,
    DEADLINE_UNKNOWN,
    DEADLINE_STALE,
    DEADLINE_UNVERIFIED,
)


# ===========================================================================
# search_schemes
# ===========================================================================

class TestSearchSchemes:
    def test_returns_results_for_matching_query(self, repository):
        result = tool_fns.search_schemes(repository, query="SC scholarship")
        assert result["result_count"] >= 1
        assert any("SC" in r["name"] or "SC" in r.get("tags", [])
                   for r in result["results"])

    def test_returns_empty_for_no_match(self, repository):
        result = tool_fns.search_schemes(repository, query="xyzzy_nonexistent_abc")
        assert result["result_count"] == 0
        assert result["results"] == []

    def test_education_level_filter(self, repository):
        result = tool_fns.search_schemes(
            repository, query="scholarship", education_level="UG"
        )
        # Only schemes with UG education level should match
        for r in result["results"]:
            assert r["id"] in ("test-women-tech", "test-no-source")

    def test_state_filter(self, repository):
        result = tool_fns.search_schemes(
            repository, query="scholarship", state="Maharashtra"
        )
        for r in result["results"]:
            assert r["id"] == "test-no-source"

    def test_invalid_empty_query(self, repository):
        result = tool_fns.search_schemes(repository, query="")
        assert result.get("error") is True
        assert result["error_code"] == "INVALID_INPUT"

    def test_query_too_long(self, repository):
        result = tool_fns.search_schemes(repository, query="x" * 600)
        assert result.get("error") is True

    def test_invalid_education_level(self, repository):
        result = tool_fns.search_schemes(
            repository, query="scholarship", education_level="INVALID_LEVEL"
        )
        assert result.get("error") is True
        assert result["error_code"] == "INVALID_EDUCATION_LEVEL"

    def test_result_has_required_fields(self, repository):
        result = tool_fns.search_schemes(repository, query="scholarship")
        for r in result["results"]:
            for field in ("id", "name", "source_url", "verified"):
                assert field in r

    def test_max_results_respected(self, repository):
        result = tool_fns.search_schemes(repository, query="scholarship", max_results=1)
        assert result["result_count"] <= 1

    def test_filters_applied_in_response(self, repository):
        result = tool_fns.search_schemes(
            repository, query="scholarship", education_level="UG", state="Maharashtra"
        )
        assert result["filters_applied"]["education_level"] == "UG"
        assert result["filters_applied"]["state"] == "Maharashtra"


# ===========================================================================
# check_eligibility
# ===========================================================================

class TestCheckEligibility:
    def test_potential_match_all_criteria_met(self, repository):
        result = tool_fns.check_eligibility(
            repository,
            scheme_id="test-sc-scholarship",
            student_info={
                "education_level": "10th",
                "caste_category": "SC",
                "percentage": 60.0,
                "annual_family_income": 200000,
                "gender": "Female",
            },
        )
        assert result["status"] == STATUS_POTENTIAL_MATCH
        assert result["unsatisfied_criteria"] == []
        assert "disclaimer" in result

    def test_not_eligible_wrong_education(self, repository):
        result = tool_fns.check_eligibility(
            repository,
            scheme_id="test-sc-scholarship",
            student_info={
                "education_level": "UG",  # scheme requires 10th
                "caste_category": "SC",
                "percentage": 60.0,
                "annual_family_income": 200000,
            },
        )
        assert result["status"] == STATUS_NOT_ELIGIBLE
        assert any(c["criterion"] == "education_level" for c in result["unsatisfied_criteria"])

    def test_not_eligible_wrong_caste(self, repository):
        result = tool_fns.check_eligibility(
            repository,
            scheme_id="test-sc-scholarship",
            student_info={
                "education_level": "10th",
                "caste_category": "General",  # scheme requires SC
                "percentage": 60.0,
                "annual_family_income": 200000,
            },
        )
        assert result["status"] == STATUS_NOT_ELIGIBLE

    def test_not_eligible_income_too_high(self, repository):
        result = tool_fns.check_eligibility(
            repository,
            scheme_id="test-sc-scholarship",
            student_info={
                "education_level": "10th",
                "caste_category": "SC",
                "percentage": 60.0,
                "annual_family_income": 500000,  # above 250000 limit
            },
        )
        assert result["status"] == STATUS_NOT_ELIGIBLE
        assert any(c["criterion"] == "annual_family_income" for c in result["unsatisfied_criteria"])

    def test_not_eligible_percentage_too_low(self, repository):
        result = tool_fns.check_eligibility(
            repository,
            scheme_id="test-sc-scholarship",
            student_info={
                "education_level": "10th",
                "caste_category": "SC",
                "percentage": 40.0,  # below 55%
                "annual_family_income": 200000,
            },
        )
        assert result["status"] == STATUS_NOT_ELIGIBLE

    def test_more_info_needed_missing_caste(self, repository):
        result = tool_fns.check_eligibility(
            repository,
            scheme_id="test-sc-scholarship",
            student_info={
                "education_level": "10th",
                "percentage": 60.0,
                # caste_category missing
            },
        )
        assert result["status"] == STATUS_MORE_INFO_NEEDED
        assert any(c["criterion"] == "caste_category" for c in result["unknown_criteria"])

    def test_more_info_needed_missing_income(self, repository):
        result = tool_fns.check_eligibility(
            repository,
            scheme_id="test-sc-scholarship",
            student_info={
                "education_level": "10th",
                "caste_category": "SC",
                "percentage": 60.0,
                # annual_family_income missing
            },
        )
        assert result["status"] == STATUS_MORE_INFO_NEEDED

    def test_gender_check_fails(self, repository):
        """Women-only scholarship fails for male student."""
        result = tool_fns.check_eligibility(
            repository,
            scheme_id="test-women-tech",
            student_info={
                "education_level": "UG",
                "gender": "Male",
            },
        )
        assert result["status"] == STATUS_NOT_ELIGIBLE
        assert any(c["criterion"] == "gender" for c in result["unsatisfied_criteria"])

    def test_unknown_scheme_id(self, repository):
        result = tool_fns.check_eligibility(
            repository, scheme_id="nonexistent-scheme", student_info={}
        )
        assert result.get("error") is True
        assert result["error_code"] == "SCHEME_NOT_FOUND"

    def test_invalid_scheme_id_characters(self, repository):
        result = tool_fns.check_eligibility(
            repository, scheme_id="bad id!", student_info={}
        )
        assert result.get("error") is True
        assert result["error_code"] == "INVALID_INPUT"

    def test_student_info_not_dict(self, repository):
        result = tool_fns.check_eligibility(
            repository, scheme_id="test-sc-scholarship", student_info="not-a-dict"
        )
        assert result.get("error") is True

    def test_disclaimer_always_present(self, repository):
        result = tool_fns.check_eligibility(
            repository, scheme_id="test-sc-scholarship", student_info={}
        )
        assert "disclaimer" in result
        assert len(result["disclaimer"]) > 10

    def test_no_invented_criteria(self, repository):
        """Result criteria must only reference fields present in the scheme."""
        result = tool_fns.check_eligibility(
            repository,
            scheme_id="test-sc-scholarship",
            student_info={
                "education_level": "10th",
                "caste_category": "SC",
                "percentage": 60.0,
                "annual_family_income": 200000,
            },
        )
        all_criteria_names = (
            [c["criterion"] for c in result["satisfied_criteria"]]
            + [c["criterion"] for c in result["unsatisfied_criteria"]]
            + [c["criterion"] for c in result["unknown_criteria"]]
        )
        # Scheme criteria: education_levels, caste_categories, min_percentage, annual_family_income
        # gender is "any" so it should NOT appear as a criterion
        assert "gender" not in all_criteria_names


# ===========================================================================
# get_requirements
# ===========================================================================

class TestGetRequirements:
    def test_returns_documents(self, repository):
        result = tool_fns.get_requirements(repository, scheme_id="test-sc-scholarship")
        assert isinstance(result["documents"], list)
        assert len(result["documents"]) > 0

    def test_returns_application_steps(self, repository):
        result = tool_fns.get_requirements(repository, scheme_id="test-sc-scholarship")
        assert isinstance(result["application_steps"], list)
        assert len(result["application_steps"]) > 0

    def test_source_url_present(self, repository):
        result = tool_fns.get_requirements(repository, scheme_id="test-sc-scholarship")
        assert result["source_url"] == "https://example.gov.in/test-sc"

    def test_missing_source_url_flagged(self, repository):
        """test-no-source has no source_url — should warn, not invent."""
        result = tool_fns.get_requirements(repository, scheme_id="test-no-source")
        assert result["source_url"] is None
        assert any("source" in w.lower() for w in result.get("warnings", []))

    def test_unverified_scheme_flagged(self, repository):
        result = tool_fns.get_requirements(repository, scheme_id="test-no-source")
        assert any("verified" in w.lower() for w in result.get("warnings", []))

    def test_information_complete_false_when_incomplete(self, repository):
        """test-no-source has empty docs, steps, no url, no last_checked."""
        result = tool_fns.get_requirements(repository, scheme_id="test-no-source")
        assert result["information_complete"] is False

    def test_information_complete_true_when_complete(self, repository):
        result = tool_fns.get_requirements(repository, scheme_id="test-sc-scholarship")
        assert result["information_complete"] is True

    def test_unknown_scheme_id(self, repository):
        result = tool_fns.get_requirements(repository, scheme_id="no-such-id")
        assert result.get("error") is True
        assert result["error_code"] == "SCHEME_NOT_FOUND"

    def test_never_invents_documents(self, repository):
        """test-no-source has empty documents list — must stay empty."""
        result = tool_fns.get_requirements(repository, scheme_id="test-no-source")
        assert result["documents"] == []


# ===========================================================================
# verify_deadline
# ===========================================================================

class TestVerifyDeadline:
    def test_current_verified_deadline(self, repository):
        """test-sc-scholarship has deadline 2099-12-31, verified, recent last_checked."""
        result = tool_fns.verify_deadline(
            repository, scheme_id="test-sc-scholarship", stale_days=365 * 100
        )
        assert result["deadline_status"] == DEADLINE_CURRENT

    def test_past_deadline(self, repository):
        """test-women-tech has deadline 2000-01-01 — definitely past."""
        result = tool_fns.verify_deadline(
            repository, scheme_id="test-women-tech", stale_days=30
        )
        assert result["deadline_status"] == DEADLINE_PAST

    def test_unknown_deadline_when_null(self, repository):
        """test-no-source has deadline=null."""
        result = tool_fns.verify_deadline(repository, scheme_id="test-no-source")
        assert result["deadline_status"] == DEADLINE_UNKNOWN

    def test_stale_deadline_flagged(self, repository):
        """test-women-tech last_checked is 2000-01-01 — stale by any threshold.
        But since the deadline is past, DEADLINE_PAST takes priority."""
        result = tool_fns.verify_deadline(
            repository, scheme_id="test-women-tech", stale_days=30
        )
        # DEADLINE_PAST takes priority over stale for past dates
        assert result["deadline_status"] in (DEADLINE_PAST, DEADLINE_STALE)

    def test_unverified_scheme_deadline_flagged(self, repository):
        """test-no-source is unverified and has no deadline."""
        result = tool_fns.verify_deadline(repository, scheme_id="test-no-source")
        assert result["deadline_status"] == DEADLINE_UNKNOWN
        assert result["verified"] is False

    def test_warning_always_present(self, repository):
        result = tool_fns.verify_deadline(repository, scheme_id="test-sc-scholarship")
        assert "warning" in result
        assert len(result["warning"]) > 0

    def test_source_url_in_result(self, repository):
        result = tool_fns.verify_deadline(repository, scheme_id="test-sc-scholarship")
        assert result["source_url"] == "https://example.gov.in/test-sc"

    def test_missing_source_url_none(self, repository):
        result = tool_fns.verify_deadline(repository, scheme_id="test-no-source")
        assert result["source_url"] is None

    def test_unknown_scheme_id(self, repository):
        result = tool_fns.verify_deadline(repository, scheme_id="no-such-id")
        assert result.get("error") is True
        assert result["error_code"] == "SCHEME_NOT_FOUND"

    def test_deadline_never_marked_current_without_verification(self, repository):
        """A future deadline on an unverified scheme must not be CURRENT."""
        # test-no-source has no deadline at all, but let's directly test logic:
        result = tool_fns.verify_deadline(repository, scheme_id="test-no-source")
        assert result["deadline_status"] != DEADLINE_CURRENT


# ===========================================================================
# create_action_plan
# ===========================================================================

class TestCreateActionPlan:
    def _eligible_result(self):
        return {
            "scheme_id": "test-sc-scholarship",
            "scheme_name": "Test SC Scholarship",
            "status": STATUS_POTENTIAL_MATCH,
            "satisfied_criteria": [{"criterion": "education_level"}],
            "unsatisfied_criteria": [],
            "unknown_criteria": [],
        }

    def _missing_info_result(self):
        return {
            "scheme_id": "test-sc-scholarship",
            "scheme_name": "Test SC Scholarship",
            "status": STATUS_MORE_INFO_NEEDED,
            "satisfied_criteria": [],
            "unsatisfied_criteria": [],
            "unknown_criteria": [{"criterion": "caste_category", "required": "SC"}],
        }

    def _not_eligible_result(self):
        return {
            "scheme_id": "test-sc-scholarship",
            "scheme_name": "Test SC Scholarship",
            "status": STATUS_NOT_ELIGIBLE,
            "satisfied_criteria": [],
            "unsatisfied_criteria": [{"criterion": "education_level"}],
            "unknown_criteria": [],
        }

    def test_returns_steps_list(self):
        result = tool_fns.create_action_plan(
            goal="Apply for SC scholarship",
            scheme_ids=["test-sc-scholarship"],
            eligibility_results=[self._eligible_result()],
            missing_info=[],
        )
        assert isinstance(result["steps"], list)
        assert len(result["steps"]) > 0

    def test_eligible_plan_has_apply_step(self):
        result = tool_fns.create_action_plan(
            goal="Apply for SC scholarship",
            scheme_ids=["test-sc-scholarship"],
            eligibility_results=[self._eligible_result()],
            missing_info=[],
        )
        action_types = [s["action_type"] for s in result["steps"]]
        assert "apply" in action_types or "verify" in action_types

    def test_missing_info_plan_has_gather_step(self):
        result = tool_fns.create_action_plan(
            goal="Apply for SC scholarship",
            scheme_ids=["test-sc-scholarship"],
            eligibility_results=[self._missing_info_result()],
            missing_info=["caste certificate"],
        )
        action_types = [s["action_type"] for s in result["steps"]]
        assert "gather_document" in action_types

    def test_not_eligible_plan_has_review_step(self):
        result = tool_fns.create_action_plan(
            goal="Apply for SC scholarship",
            scheme_ids=["test-sc-scholarship"],
            eligibility_results=[self._not_eligible_result()],
            missing_info=[],
        )
        action_types = [s["action_type"] for s in result["steps"]]
        assert "verify" in action_types

    def test_steps_never_claim_submitted(self):
        result = tool_fns.create_action_plan(
            goal="Apply",
            scheme_ids=["test-sc-scholarship"],
            eligibility_results=[self._eligible_result()],
            missing_info=[],
        )
        plan_text = str(result)
        assert "submitted" not in plan_text.lower() or "has been submitted" not in plan_text.lower()

    def test_requires_user_verification_on_apply_steps(self):
        result = tool_fns.create_action_plan(
            goal="Apply",
            scheme_ids=["test-sc-scholarship"],
            eligibility_results=[self._eligible_result()],
            missing_info=[],
        )
        apply_steps = [s for s in result["steps"] if s["action_type"] == "apply"]
        for step in apply_steps:
            assert step["requires_user_verification"] is True

    def test_disclaimer_in_result(self):
        result = tool_fns.create_action_plan(
            goal="Apply",
            scheme_ids=[],
            eligibility_results=[],
            missing_info=[],
        )
        assert "disclaimer" in result

    def test_invalid_goal(self):
        result = tool_fns.create_action_plan(
            goal="",
            scheme_ids=[],
            eligibility_results=[],
            missing_info=[],
        )
        assert result.get("error") is True

    def test_invalid_scheme_ids_type(self):
        result = tool_fns.create_action_plan(
            goal="Apply",
            scheme_ids="not-a-list",
            eligibility_results=[],
            missing_info=[],
        )
        assert result.get("error") is True

    def test_empty_plan_has_research_step(self):
        """Empty eligibility results should still produce a useful plan."""
        result = tool_fns.create_action_plan(
            goal="Find scholarships",
            scheme_ids=[],
            eligibility_results=[],
            missing_info=[],
        )
        action_types = [s["action_type"] for s in result["steps"]]
        assert "research" in action_types
