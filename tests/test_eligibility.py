"""
test_eligibility.py — deterministic eligibility engine unit tests.

Table-driven coverage of every criterion evaluator, education-level
normalisation, and disability support.
"""

from __future__ import annotations

import pytest
from backend.schemas import Criterion
from backend.eligibility import (
    ELIGIBILITY_REGISTRY,
    evaluate_scheme,
    normalise_education_level,
)


def _criterion(field: str, operator: str = "eq", value=None) -> Criterion:
    return Criterion(field=field, operator=operator, value=value)


# ---------------------------------------------------------------------------
# Education-level normalisation
# ---------------------------------------------------------------------------

class TestEducationNormalisation:
    @pytest.mark.parametrize("raw,expected", [
        ("UG", "ug"),
        ("BTech", "ug"),
        ("B.Tech", "ug"),
        ("B.Tech.", "ug"),
        ("BE", "ug"),
        ("BSc", "ug"),
        ("undergraduate", "ug"),
        ("bachelor", "ug"),
        ("PG", "pg"),
        ("MTech", "pg"),
        ("MSc", "pg"),
        ("MBA", "pg"),
        ("postgraduate", "pg"),
        ("Class 10", "10th"),
        ("class 10", "10th"),
        ("10th", "10th"),
        ("matric", "10th"),
        ("ssc", "10th"),
        ("12th", "12th"),
        ("HSC", "12th"),
        ("intermediate", "12th"),
        ("diploma", "diploma"),
        ("phd", "phd"),
        ("doctorate", "phd"),
        ("any", "any"),
    ])
    def test_known_aliases_normalise(self, raw, expected):
        assert normalise_education_level(raw) == expected

    def test_unknown_input_returns_none(self):
        assert normalise_education_level("random stuff") is None
        assert normalise_education_level("") is None
        assert normalise_education_level(42) is None


# ---------------------------------------------------------------------------
# Individual criterion evaluators
# ---------------------------------------------------------------------------

class TestEducationCriterion:
    def test_met_exact_match(self):
        r = ELIGIBILITY_REGISTRY["education_level"](
            _criterion("education_level", "in", ["10th"]), {"education_level": "10th"}
        )
        assert r.status == "met"

    def test_met_normalised_alias(self):
        r = ELIGIBILITY_REGISTRY["education_level"](
            _criterion("education_level", "in", ["UG"]), {"education_level": "BTech"}
        )
        assert r.status == "met"

    def test_not_met_mismatch(self):
        r = ELIGIBILITY_REGISTRY["education_level"](
            _criterion("education_level", "in", ["10th"]), {"education_level": "12th"}
        )
        assert r.status == "not_met"

    def test_unknown_when_missing(self):
        r = ELIGIBILITY_REGISTRY["education_level"](
            _criterion("education_level", "in", ["10th"]), {}
        )
        assert r.status == "unknown"

    def test_unknown_when_unrecognised(self):
        r = ELIGIBILITY_REGISTRY["education_level"](
            _criterion("education_level", "in", ["10th"]), {"education_level": "abc"}
        )
        assert r.status == "unknown"


class TestStateCriterion:
    def test_met(self):
        r = ELIGIBILITY_REGISTRY["state"](
            _criterion("state", "eq", "Maharashtra"), {"state": "maharashtra"}
        )
        assert r.status == "met"

    def test_not_met(self):
        r = ELIGIBILITY_REGISTRY["state"](
            _criterion("state", "eq", "Maharashtra"), {"state": "Karnataka"}
        )
        assert r.status == "not_met"

    def test_unknown(self):
        r = ELIGIBILITY_REGISTRY["state"](
            _criterion("state", "eq", "Maharashtra"), {}
        )
        assert r.status == "unknown"


class TestCasteCriterion:
    def test_met(self):
        r = ELIGIBILITY_REGISTRY["caste_category"](
            _criterion("caste_category", "in", ["SC"]), {"caste_category": "sc"}
        )
        assert r.status == "met"

    def test_not_met(self):
        r = ELIGIBILITY_REGISTRY["caste_category"](
            _criterion("caste_category", "in", ["SC"]), {"caste_category": "OBC"}
        )
        assert r.status == "not_met"


class TestMinPercentageCriterion:
    def test_met_above_threshold(self):
        r = ELIGIBILITY_REGISTRY["min_percentage"](
            _criterion("min_percentage", "gte", 55.0), {"percentage": 80}
        )
        assert r.status == "met"

    def test_met_exact_threshold(self):
        r = ELIGIBILITY_REGISTRY["min_percentage"](
            _criterion("min_percentage", "gte", 55.0), {"percentage": 55.0}
        )
        assert r.status == "met"

    def test_not_met_below(self):
        r = ELIGIBILITY_REGISTRY["min_percentage"](
            _criterion("min_percentage", "gte", 55.0), {"percentage": 40}
        )
        assert r.status == "not_met"


class TestIncomeCriterion:
    def test_met_within_limit(self):
        r = ELIGIBILITY_REGISTRY["annual_family_income"](
            _criterion("annual_family_income", "lte", 250000), {"annual_family_income": 200000}
        )
        assert r.status == "met"

    def test_not_met_above_limit(self):
        r = ELIGIBILITY_REGISTRY["annual_family_income"](
            _criterion("annual_family_income", "lte", 250000), {"annual_family_income": 300000}
        )
        assert r.status == "not_met"


class TestGenderCriterion:
    def test_met(self):
        r = ELIGIBILITY_REGISTRY["gender"](
            _criterion("gender", "eq", "Female"), {"gender": "female"}
        )
        assert r.status == "met"

    def test_not_met(self):
        r = ELIGIBILITY_REGISTRY["gender"](
            _criterion("gender", "eq", "Female"), {"gender": "Male"}
        )
        assert r.status == "not_met"


class TestDisabilityCriterion:
    def test_met_required_and_present(self):
        r = ELIGIBILITY_REGISTRY["disability_required"](
            _criterion("disability_required", "eq", True), {"disability": True}
        )
        assert r.status == "met"

    def test_not_met_required_but_absent(self):
        r = ELIGIBILITY_REGISTRY["disability_required"](
            _criterion("disability_required", "eq", True), {"disability": False}
        )
        assert r.status == "not_met"

    def test_unknown_when_not_provided(self):
        r = ELIGIBILITY_REGISTRY["disability_required"](
            _criterion("disability_required", "eq", True), {}
        )
        assert r.status == "unknown"


# ---------------------------------------------------------------------------
# Full-scheme evaluation (mixed criteria)
# ---------------------------------------------------------------------------

class TestEvaluateScheme:
    def test_all_met_returns_potential_match(self):
        criteria = [
            _criterion("education_level", "in", ["10th"]),
            _criterion("caste_category", "in", ["SC"]),
            _criterion("min_percentage", "gte", 55.0),
        ]
        student = {"education_level": "10th", "caste_category": "SC", "percentage": 80}
        result = evaluate_scheme(criteria, student)
        assert result["status"] == "potential_match"
        assert len(result["satisfied_criteria"]) == 3
        assert result["unsatisfied_criteria"] == []
        assert result["unknown_criteria"] == []

    def test_any_failure_is_not_eligible(self):
        criteria = [
            _criterion("education_level", "in", ["10th"]),
            _criterion("min_percentage", "gte", 55.0),
        ]
        student = {"education_level": "10th", "percentage": 30}
        result = evaluate_scheme(criteria, student)
        assert result["status"] == "not_eligible_based_on_provided_information"
        assert len(result["unsatisfied_criteria"]) == 1

    def test_unknown_only_is_more_info_needed(self):
        criteria = [_criterion("education_level", "in", ["10th"])]
        student = {}
        result = evaluate_scheme(criteria, student)
        assert result["status"] == "more_information_needed"

    def test_unknown_evaluator_field(self):
        criteria = [_criterion("future_criterion", "eq", "yes")]
        result = evaluate_scheme(criteria, {})
        assert result["status"] == "more_information_needed"
        assert result["unknown_criteria"][0]["criterion"] == "future_criterion"

    def test_disclaimer_always_present(self):
        result = evaluate_scheme([], {})
        assert "disclaimer" in result

    def test_btech_normalized_for_ug_scheme(self):
        criteria = [_criterion("education_level", "in", ["UG"])]
        student = {"education_level": "BTech"}
        result = evaluate_scheme(criteria, student)
        assert result["status"] == "potential_match"