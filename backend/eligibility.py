"""
eligibility.py — EduSaarthi AI deterministic eligibility engine.

This module implements a reliable, testable eligibility engine that evaluates
student profiles against scholarship criteria using deterministic Python logic.
No LLM judgment is used for eligibility decisions.

Evaluation states for each criterion:
  - "met": student information satisfies the published rule
  - "not_met": student information violates the published rule
  - "unknown": required student info or reliable scheme rule is missing/ambiguous

Overall outcomes:
  - "eligible": all mandatory criteria met, all necessary rules verified,
    no required checks unresolved
  - "ineligible": at least one verified mandatory criterion not met
  - "needs_information": no verified mandatory failure, but required details
    or rules remain unknown
  - "needs_review": scheme contains unsupported, contradictory, or ambiguous
    rules that cannot be evaluated reliably
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum

from backend.schemas import EligibilityCriteria, SchemeRecord


class CriterionState(str, Enum):
    """Evaluation state for an individual eligibility criterion."""
    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"


class OverallOutcome(str, Enum):
    """Overall eligibility outcome for a scheme."""
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    NEEDS_INFORMATION = "needs_information"
    NEEDS_REVIEW = "needs_review"


@dataclass
class CriterionEvaluation:
    """
    Result of evaluating a single criterion against student info and scheme data.
    """
    criterion: str                           # e.g., "education_level"
    state: CriterionState                    # met / not_met / unknown
    student_value: Optional[Any] = None      # value provided by student (or None)
    published_requirement: Optional[str] = None  # human-readable requirement
    explanation: str = ""                    # concise explanation of the evaluation
    evidence_reference: Optional[str] = None # source_url or "knowledge_base"
    missing_info_reason: Optional[str] = None   # why info is missing (if unknown)
    unsupported_condition: Optional[str] = None # why review is needed (if needs_review)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "criterion": self.criterion,
            "state": self.state.value,
            "student_value": self.student_value,
            "published_requirement": self.published_requirement,
            "explanation": self.explanation,
            "evidence_reference": self.evidence_reference,
            "missing_info_reason": self.missing_info_reason,
            "unsupported_condition": self.unsupported_condition,
        }


@dataclass
class EligibilityResult:
    """
    Complete eligibility evaluation result for a scheme.
    """
    scheme_id: str
    scheme_name: str
    outcome: OverallOutcome
    criteria: list[CriterionEvaluation] = field(default_factory=list)
    disclaimer: str = (
        "This is an assessment against published criteria only, not an official "
        "award decision. Eligibility is determined solely by the scheme's "
        "administering authority. Please verify all criteria on the official portal "
        "before applying."
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "scheme_id": self.scheme_id,
            "scheme_name": self.scheme_name,
            "outcome": self.outcome.value,
            "criteria": [c.to_dict() for c in self.criteria],
            "disclaimer": self.disclaimer,
        }


# ---------------------------------------------------------------------------
# Helper functions for criterion evaluation
# ---------------------------------------------------------------------------

def _is_student_value_missing(value: Any) -> bool:
    """Check if a student-provided value is effectively missing (None or empty string)."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _normalize_str(value: Optional[str]) -> Optional[str]:
    """Normalize string for comparison: strip whitespace, lower case.
    
    Empty strings are treated as missing (None).
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped.lower()


def _parse_float(value: Any) -> Optional[float]:
    """Safely parse a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_inr(amount: float) -> str:
    """Format INR amount with commas."""
    return f"₹{amount:,.0f}"


def _format_pct(value: float) -> str:
    """Format percentage value."""
    return f"{value}%"


def _get_evidence_ref(scheme: SchemeRecord) -> str:
    """Get evidence reference for a scheme."""
    if scheme.source_url:
        return scheme.source_url
    return "knowledge_base"


def _is_any_restriction(values: Optional[list[str]]) -> bool:
    """Check if a list of allowed values means 'no restriction'."""
    if not values:
        return True
    normalized = [v.lower().strip() for v in values]
    return "any" in normalized


# ---------------------------------------------------------------------------
# Individual criterion evaluators
# ---------------------------------------------------------------------------

def evaluate_education_level(
    scheme: SchemeRecord,
    student_info: dict[str, Any],
) -> CriterionEvaluation:
    """
    Evaluate education_level criterion.
    
    Scheme rule: education_levels list (or None for no restriction).
    Student provides: education_level string.
    Comparison: exact match (case-insensitive) against allowed list.
    """
    criteria = scheme.criteria
    evidence_ref = _get_evidence_ref(scheme)
    
    # No restriction on scheme side
    if not criteria.education_levels or _is_any_restriction(criteria.education_levels):
        return CriterionEvaluation(
            criterion="education_level",
            state=CriterionState.MET,
            student_value=student_info.get("education_level"),
            published_requirement="No restriction",
            explanation="Scheme has no education level restriction.",
            evidence_reference=evidence_ref,
        )
    
    student_edu = student_info.get("education_level")
    if _is_student_value_missing(student_edu):
        return CriterionEvaluation(
            criterion="education_level",
            state=CriterionState.UNKNOWN,
            student_value=None,
            published_requirement=f"One of: {criteria.education_levels}",
            explanation="Student did not provide education level.",
            evidence_reference=evidence_ref,
            missing_info_reason="education_level not provided in student profile",
        )
    
    student_edu_norm = _normalize_str(student_edu)
    allowed_norm = [_normalize_str(v) for v in criteria.education_levels]
    
    if student_edu_norm in allowed_norm:
        return CriterionEvaluation(
            criterion="education_level",
            state=CriterionState.MET,
            student_value=student_edu,
            published_requirement=f"One of: {criteria.education_levels}",
            explanation=f"Education level '{student_edu}' matches scheme requirement.",
            evidence_reference=evidence_ref,
        )
    else:
        return CriterionEvaluation(
            criterion="education_level",
            state=CriterionState.NOT_MET,
            student_value=student_edu,
            published_requirement=f"One of: {criteria.education_levels}",
            explanation=f"Education level '{student_edu}' does not match any allowed level: {criteria.education_levels}.",
            evidence_reference=evidence_ref,
        )


def evaluate_state(
    scheme: SchemeRecord,
    student_info: dict[str, Any],
) -> CriterionEvaluation:
    """
    Evaluate state/domicile criterion.
    
    Scheme rule: state string (or None for all-India).
    Student provides: state string.
    Comparison: exact match (case-insensitive).
    """
    criteria = scheme.criteria
    evidence_ref = _get_evidence_ref(scheme)
    
    # No state restriction (all-India scheme)
    if not criteria.state:
        return CriterionEvaluation(
            criterion="state",
            state=CriterionState.MET,
            student_value=student_info.get("state"),
            published_requirement="All India (no state restriction)",
            explanation="Scheme is open to students from all states.",
            evidence_reference=evidence_ref,
        )
    
    student_state = student_info.get("state")
    if _is_student_value_missing(student_state):
        return CriterionEvaluation(
            criterion="state",
            state=CriterionState.UNKNOWN,
            student_value=None,
            published_requirement=criteria.state,
            explanation="Student did not provide state of domicile.",
            evidence_reference=evidence_ref,
            missing_info_reason="state not provided in student profile",
        )
    
    student_state_norm = _normalize_str(student_state)
    scheme_state_norm = _normalize_str(criteria.state)
    
    if student_state_norm == scheme_state_norm:
        return CriterionEvaluation(
            criterion="state",
            state=CriterionState.MET,
            student_value=student_state,
            published_requirement=criteria.state,
            explanation=f"State '{student_state}' matches scheme requirement.",
            evidence_reference=evidence_ref,
        )
    else:
        return CriterionEvaluation(
            criterion="state",
            state=CriterionState.NOT_MET,
            student_value=student_state,
            published_requirement=criteria.state,
            explanation=f"State '{student_state}' does not match required state '{criteria.state}'.",
            evidence_reference=evidence_ref,
        )


def evaluate_caste_category(
    scheme: SchemeRecord,
    student_info: dict[str, Any],
) -> CriterionEvaluation:
    """
    Evaluate caste_category criterion.
    
    Scheme rule: caste_categories list (or None/["any"] for no restriction).
    Student provides: caste_category string.
    Comparison: case-insensitive match against allowed list.
    """
    criteria = scheme.criteria
    evidence_ref = _get_evidence_ref(scheme)
    
    # No restriction on scheme side
    if not criteria.caste_categories or _is_any_restriction(criteria.caste_categories):
        return CriterionEvaluation(
            criterion="caste_category",
            state=CriterionState.MET,
            student_value=student_info.get("caste_category"),
            published_requirement="No restriction",
            explanation="Scheme has no caste category restriction.",
            evidence_reference=evidence_ref,
        )
    
    student_caste = student_info.get("caste_category")
    if _is_student_value_missing(student_caste):
        return CriterionEvaluation(
            criterion="caste_category",
            state=CriterionState.UNKNOWN,
            student_value=None,
            published_requirement=f"One of: {criteria.caste_categories}",
            explanation="Student did not provide caste category.",
            evidence_reference=evidence_ref,
            missing_info_reason="caste_category not provided in student profile",
        )
    
    student_caste_norm = _normalize_str(student_caste)
    allowed_norm = [_normalize_str(v) for v in criteria.caste_categories]
    
    if student_caste_norm in allowed_norm:
        return CriterionEvaluation(
            criterion="caste_category",
            state=CriterionState.MET,
            student_value=student_caste,
            published_requirement=f"One of: {criteria.caste_categories}",
            explanation=f"Caste category '{student_caste}' matches scheme requirement.",
            evidence_reference=evidence_ref,
        )
    else:
        return CriterionEvaluation(
            criterion="caste_category",
            state=CriterionState.NOT_MET,
            student_value=student_caste,
            published_requirement=f"One of: {criteria.caste_categories}",
            explanation=f"Caste category '{student_caste}' does not match any allowed category: {criteria.caste_categories}.",
            evidence_reference=evidence_ref,
        )


def evaluate_min_percentage(
    scheme: SchemeRecord,
    student_info: dict[str, Any],
) -> CriterionEvaluation:
    """
    Evaluate minimum percentage criterion.
    
    Scheme rule: min_percentage (float, 0-100, or None for no restriction).
    Student provides: percentage (float).
    Comparison: student_percentage >= min_percentage.
    """
    criteria = scheme.criteria
    evidence_ref = _get_evidence_ref(scheme)
    
    # No restriction on scheme side
    if criteria.min_percentage is None:
        return CriterionEvaluation(
            criterion="percentage",
            state=CriterionState.MET,
            student_value=student_info.get("percentage"),
            published_requirement="No minimum percentage requirement",
            explanation="Scheme has no minimum percentage requirement.",
            evidence_reference=evidence_ref,
        )
    
    student_pct_raw = student_info.get("percentage")
    student_pct = _parse_float(student_pct_raw)
    
    if student_pct is None:
        return CriterionEvaluation(
            criterion="percentage",
            state=CriterionState.UNKNOWN,
            student_value=student_pct_raw,
            published_requirement=f">= {_format_pct(criteria.min_percentage)}",
            explanation="Student did not provide a valid percentage.",
            evidence_reference=evidence_ref,
            missing_info_reason="percentage not provided or not a valid number",
        )
    
    # Compare: student_pct >= min_percentage
    if student_pct >= criteria.min_percentage:
        return CriterionEvaluation(
            criterion="percentage",
            state=CriterionState.MET,
            student_value=_format_pct(student_pct),
            published_requirement=f">= {_format_pct(criteria.min_percentage)}",
            explanation=f"Percentage {_format_pct(student_pct)} meets minimum requirement of {_format_pct(criteria.min_percentage)}.",
            evidence_reference=evidence_ref,
        )
    else:
        return CriterionEvaluation(
            criterion="percentage",
            state=CriterionState.NOT_MET,
            student_value=_format_pct(student_pct),
            published_requirement=f">= {_format_pct(criteria.min_percentage)}",
            explanation=f"Percentage {_format_pct(student_pct)} is below minimum requirement of {_format_pct(criteria.min_percentage)}.",
            evidence_reference=evidence_ref,
        )


def evaluate_annual_family_income(
    scheme: SchemeRecord,
    student_info: dict[str, Any],
) -> CriterionEvaluation:
    """
    Evaluate annual family income criterion.
    
    Scheme rule: annual_family_income_max (float, INR, or None for no restriction).
    Student provides: annual_family_income (float, INR).
    Comparison: student_income <= annual_family_income_max.
    """
    criteria = scheme.criteria
    evidence_ref = _get_evidence_ref(scheme)
    
    # No restriction on scheme side
    if criteria.annual_family_income_max is None:
        return CriterionEvaluation(
            criterion="annual_family_income",
            state=CriterionState.MET,
            student_value=student_info.get("annual_family_income"),
            published_requirement="No income ceiling",
            explanation="Scheme has no maximum family income restriction.",
            evidence_reference=evidence_ref,
        )
    
    student_income_raw = student_info.get("annual_family_income")
    student_income = _parse_float(student_income_raw)
    
    if student_income is None:
        return CriterionEvaluation(
            criterion="annual_family_income",
            state=CriterionState.UNKNOWN,
            student_value=student_income_raw,
            published_requirement=f"<= {_format_inr(criteria.annual_family_income_max)}",
            explanation="Student did not provide a valid annual family income.",
            evidence_reference=evidence_ref,
            missing_info_reason="annual_family_income not provided or not a valid number",
        )
    
    # Compare: student_income <= max_income
    if student_income <= criteria.annual_family_income_max:
        return CriterionEvaluation(
            criterion="annual_family_income",
            state=CriterionState.MET,
            student_value=_format_inr(student_income),
            published_requirement=f"<= {_format_inr(criteria.annual_family_income_max)}",
            explanation=f"Annual family income {_format_inr(student_income)} is within the limit of {_format_inr(criteria.annual_family_income_max)}.",
            evidence_reference=evidence_ref,
        )
    else:
        return CriterionEvaluation(
            criterion="annual_family_income",
            state=CriterionState.NOT_MET,
            student_value=_format_inr(student_income),
            published_requirement=f"<= {_format_inr(criteria.annual_family_income_max)}",
            explanation=f"Annual family income {_format_inr(student_income)} exceeds the maximum allowed {_format_inr(criteria.annual_family_income_max)}.",
            evidence_reference=evidence_ref,
        )


def evaluate_gender(
    scheme: SchemeRecord,
    student_info: dict[str, Any],
) -> CriterionEvaluation:
    """
    Evaluate gender criterion.
    
    Scheme rule: gender string (or None/"any" for no restriction).
    Student provides: gender string.
    Comparison: exact match (case-insensitive).
    """
    criteria = scheme.criteria
    evidence_ref = _get_evidence_ref(scheme)
    
    # No restriction on scheme side
    if not criteria.gender or _normalize_str(criteria.gender) == "any":
        return CriterionEvaluation(
            criterion="gender",
            state=CriterionState.MET,
            student_value=student_info.get("gender"),
            published_requirement="No restriction",
            explanation="Scheme has no gender restriction.",
            evidence_reference=evidence_ref,
        )
    
    student_gender = student_info.get("gender")
    if _is_student_value_missing(student_gender):
        return CriterionEvaluation(
            criterion="gender",
            state=CriterionState.UNKNOWN,
            student_value=None,
            published_requirement=criteria.gender,
            explanation="Student did not provide gender.",
            evidence_reference=evidence_ref,
            missing_info_reason="gender not provided in student profile",
        )
    
    student_gender_norm = _normalize_str(student_gender)
    scheme_gender_norm = _normalize_str(criteria.gender)
    
    if student_gender_norm == scheme_gender_norm:
        return CriterionEvaluation(
            criterion="gender",
            state=CriterionState.MET,
            student_value=student_gender,
            published_requirement=criteria.gender,
            explanation=f"Gender '{student_gender}' matches scheme requirement.",
            evidence_reference=evidence_ref,
        )
    else:
        return CriterionEvaluation(
            criterion="gender",
            state=CriterionState.NOT_MET,
            student_value=student_gender,
            published_requirement=criteria.gender,
            explanation=f"Gender '{student_gender}' does not match required gender '{criteria.gender}'.",
            evidence_reference=evidence_ref,
        )


def evaluate_disability_required(
    scheme: SchemeRecord,
    student_info: dict[str, Any],
) -> CriterionEvaluation:
    """
    Evaluate disability_required criterion.
    
    Scheme rule: disability_required (True/False/None).
    - None: not specified / no restriction
    - True: disability certificate required
    - False: disability certificate not required
    Student provides: disability (bool).
    Comparison: if True required, student must have disability=True.
    """
    criteria = scheme.criteria
    evidence_ref = _get_evidence_ref(scheme)
    
    # No restriction specified
    if criteria.disability_required is None:
        return CriterionEvaluation(
            criterion="disability",
            state=CriterionState.MET,
            student_value=student_info.get("disability"),
            published_requirement="Not specified",
            explanation="Scheme does not specify disability requirement.",
            evidence_reference=evidence_ref,
        )
    
    student_disability = student_info.get("disability")
    
    if criteria.disability_required is True:
        # Disability certificate required
        if student_disability is None:
            return CriterionEvaluation(
                criterion="disability",
                state=CriterionState.UNKNOWN,
                student_value=None,
                published_requirement="Disability certificate required",
                explanation="Scheme requires disability certificate; student did not provide disability status.",
                evidence_reference=evidence_ref,
                missing_info_reason="disability status not provided",
            )
        elif student_disability is True:
            return CriterionEvaluation(
                criterion="disability",
                state=CriterionState.MET,
                student_value=True,
                published_requirement="Disability certificate required",
                explanation="Student has disability certificate as required.",
                evidence_reference=evidence_ref,
            )
        else:
            return CriterionEvaluation(
                criterion="disability",
                state=CriterionState.NOT_MET,
                student_value=False,
                published_requirement="Disability certificate required",
                explanation="Scheme requires disability certificate; student does not have one.",
                evidence_reference=evidence_ref,
            )
    else:
        # criteria.disability_required is False - disability not required
        return CriterionEvaluation(
            criterion="disability",
            state=CriterionState.MET,
            student_value=student_disability,
            published_requirement="Disability certificate not required",
            explanation="Scheme does not require disability certificate.",
            evidence_reference=evidence_ref,
        )


def evaluate_notes(
    scheme: SchemeRecord,
    student_info: dict[str, Any],
) -> Optional[CriterionEvaluation]:
    """
    Evaluate free-form notes criterion.
    
    Notes are informational only and cannot be deterministically evaluated.
    They are returned as an 'unknown' criterion with needs_review flag
    if they contain evaluable conditions.
    """
    criteria = scheme.criteria
    evidence_ref = _get_evidence_ref(scheme)
    
    if not criteria.notes:
        return None
    
    # Check if notes contain evaluable conditions we don't support
    # For now, treat all notes as informational requiring manual review
    return CriterionEvaluation(
        criterion="notes",
        state=CriterionState.UNKNOWN,
        student_value=None,
        published_requirement=criteria.notes,
        explanation="Free-form notes cannot be automatically evaluated. Manual review required.",
        evidence_reference=evidence_ref,
        unsupported_condition="Free-form notes criterion requires manual verification",
    )


# ---------------------------------------------------------------------------
# Main eligibility engine
# ---------------------------------------------------------------------------

# Order of evaluation matters for consistent output
CRITERION_EVALUATORS = [
    ("education_level", evaluate_education_level),
    ("state", evaluate_state),
    ("caste_category", evaluate_caste_category),
    ("percentage", evaluate_min_percentage),
    ("annual_family_income", evaluate_annual_family_income),
    ("gender", evaluate_gender),
    ("disability", evaluate_disability_required),
    # notes is handled separately as it's optional/informational
]

# Notes is NOT a mandatory criterion - it's informational only
MANDATORY_CRITERIA = {
    "education_level",
    "state",
    "caste_category",
    "percentage",
    "annual_family_income",
    "gender",
    "disability",
}


def evaluate_eligibility(
    scheme: SchemeRecord,
    student_info: dict[str, Any],
) -> EligibilityResult:
    """
    Evaluate student eligibility for a scheme using deterministic logic.
    
    This is the main entry point for the eligibility engine. It evaluates
    each criterion independently and computes the overall outcome.
    
    Args:
        scheme: The SchemeRecord to evaluate against.
        student_info: Dictionary with student profile data.
    
    Returns:
        EligibilityResult with per-criterion evaluations and overall outcome.
    """
    criteria_evals: list[CriterionEvaluation] = []
    
    # Evaluate each structured criterion ONLY if the scheme specifies it
    for criterion_name, evaluator in CRITERION_EVALUATORS:
        # Skip criteria that the scheme doesn't actually restrict
        if not _is_criterion_specified(scheme.criteria, criterion_name):
            continue
        eval_result = evaluator(scheme, student_info)
        criteria_evals.append(eval_result)
    
    # Evaluate notes (informational only) if present
    notes_eval = evaluate_notes(scheme, student_info)
    if notes_eval:
        criteria_evals.append(notes_eval)
    
    # Determine overall outcome
    outcome = _determine_outcome(criteria_evals, scheme)
    
    return EligibilityResult(
        scheme_id=scheme.id,
        scheme_name=scheme.name,
        outcome=outcome,
        criteria=criteria_evals,
    )


def _determine_outcome(
    criteria_evals: list[CriterionEvaluation],
    scheme: SchemeRecord,
) -> OverallOutcome:
    """
    Determine overall eligibility outcome from criterion evaluations.
    
    Logic (in priority order):
    1. If any MANDATORY criterion is NOT_MET → INELIGIBLE
    2. If any criterion has unsupported_condition → NEEDS_REVIEW
    3. If any MANDATORY criterion is UNKNOWN → NEEDS_INFORMATION
    4. Else → ELIGIBLE
    
    Notes:
    - Only criteria that the scheme actually specifies (non-None) are mandatory.
    - Criteria with "any"/no restriction are treated as MET and not mandatory.
    - Free-form notes (with unsupported_condition) trigger NEEDS_REVIEW.
    """
    has_not_met = False
    has_unknown_mandatory = False
    has_unsupported = False
    
    for eval_ in criteria_evals:
        is_mandatory = eval_.criterion in MANDATORY_CRITERIA
        
        # Check if this criterion was actually specified by the scheme
        scheme_criteria = scheme.criteria
        criterion_specified = _is_criterion_specified(scheme_criteria, eval_.criterion)
        
        if not criterion_specified:
            continue  # Not a requirement for this scheme
        
        if eval_.state == CriterionState.NOT_MET:
            has_not_met = True
        elif eval_.state == CriterionState.UNKNOWN:
            if eval_.unsupported_condition:
                has_unsupported = True
            elif is_mandatory or eval_.missing_info_reason:
                has_unknown_mandatory = True
        elif eval_.unsupported_condition:
            has_unsupported = True
    
    if has_not_met:
        return OverallOutcome.INELIGIBLE
    if has_unsupported:
        return OverallOutcome.NEEDS_REVIEW
    if has_unknown_mandatory:
        return OverallOutcome.NEEDS_INFORMATION
    return OverallOutcome.ELIGIBLE


def _is_criterion_specified(criteria: EligibilityCriteria, criterion_name: str) -> bool:
    """Check if a scheme actually specifies a given criterion (not None/any)."""
    if criterion_name == "education_level":
        return criteria.education_levels is not None and not _is_any_restriction(criteria.education_levels)
    if criterion_name == "state":
        return criteria.state is not None
    if criterion_name == "caste_category":
        return criteria.caste_categories is not None and not _is_any_restriction(criteria.caste_categories)
    if criterion_name == "percentage":
        return criteria.min_percentage is not None
    if criterion_name == "annual_family_income":
        return criteria.annual_family_income_max is not None
    if criterion_name == "gender":
        return criteria.gender is not None and _normalize_str(criteria.gender) != "any"
    if criterion_name == "disability":
        return criteria.disability_required is not None
    if criterion_name == "notes":
        return criteria.notes is not None and criteria.notes.strip() != ""
    return False


# ---------------------------------------------------------------------------
# Adapter for the existing check_eligibility tool interface
# ---------------------------------------------------------------------------

def evaluate_eligibility_for_tool(
    scheme: SchemeRecord,
    student_info: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate eligibility and return format compatible with existing check_eligibility tool.
    
    This adapter maintains backward compatibility while using the new engine.
    """
    result = evaluate_eligibility(scheme, student_info)
    
    # Map new outcome to legacy status constants
    from backend.tools import (
        STATUS_POTENTIAL_MATCH,
        STATUS_NOT_ELIGIBLE,
        STATUS_MORE_INFO_NEEDED,
    )
    
    outcome_map = {
        OverallOutcome.ELIGIBLE: STATUS_POTENTIAL_MATCH,
        OverallOutcome.INELIGIBLE: STATUS_NOT_ELIGIBLE,
        OverallOutcome.NEEDS_INFORMATION: STATUS_MORE_INFO_NEEDED,
        OverallOutcome.NEEDS_REVIEW: STATUS_MORE_INFO_NEEDED,  # Treat review as needing info
    }
    
    # Convert criteria evaluations to legacy format
    satisfied = []
    unsatisfied = []
    unknown = []
    
    for eval_ in result.criteria:
        legacy_item = {
            "criterion": eval_.criterion,
            "required": eval_.published_requirement,
            "provided": eval_.student_value,
        }
        if eval_.explanation:
            legacy_item["note"] = eval_.explanation
        
        if eval_.state == CriterionState.MET:
            satisfied.append(legacy_item)
        elif eval_.state == CriterionState.NOT_MET:
            unsatisfied.append(legacy_item)
        else:
            unknown.append(legacy_item)
    
    status = outcome_map.get(result.outcome, STATUS_MORE_INFO_NEEDED)
    
    return {
        "scheme_id": result.scheme_id,
        "scheme_name": result.scheme_name,
        "status": status,
        "satisfied_criteria": satisfied,
        "unsatisfied_criteria": unsatisfied,
        "unknown_criteria": unknown,
        "additional_notes": scheme.criteria.notes,
        "disclaimer": result.disclaimer,
        # New structured fields (optional, for enhanced frontend)
        "outcome": result.outcome.value,
        "criteria_details": [c.to_dict() for c in result.criteria],
    }