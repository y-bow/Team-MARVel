"""
eligibility.py — deterministic eligibility engine for EduSaarthi AI.

Design rules:
  - Never treats missing information as satisfying a criterion.
  - Never invents criteria absent from the data.
  - Never involves the LLM in the decision path.
  - Returns three statuses per criterion: met, not_met, unknown.
  - Each criterion field has a registered evaluator — unknown fields fail early.

The education normalisation maps common student phrasing ("BTech", "Class 10")
to canonical tokens the data uses ("UG", "10th"). Unknown inputs are left as-is
and result in an "unknown" per-criterion result when no data match is found.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.schemas import Criterion, CRITERION_FIELDS


# ---------------------------------------------------------------------------
# Education-level normalisation
# ---------------------------------------------------------------------------

_EDUCATION_ALIASES: dict[str, str] = {
    # primary / secondary
    "5th": "5th", "fifth": "5th", "class 5": "5th",
    "6th": "6th", "sixth": "6th", "class 6": "6th",
    "7th": "7th", "seventh": "7th", "class 7": "7th",
    "8th": "8th", "eighth": "8th", "class 8": "8th",
    # high-school
    "9th": "9th", "ninth": "9th", "class 9": "9th",
    "10th": "10th", "tenth": "10th", "class 10": "10th", "matric": "10th", "ssc": "10th",
    "11th": "11th", "eleventh": "11th", "class 11": "11th",
    "12th": "12th", "twelfth": "12th", "class 12": "12th", "hsc": "12th", "intermediate": "12th",
    # higher education
    "ug": "ug", "undergraduate": "ug", "bachelor": "ug", "bachelors": "ug",
    "btech": "ug", "b.tech": "ug", "be": "ug", "b.e": "ug", "bsc": "ug", "b.sc": "ug",
    "ba": "ug", "b.a": "ug", "bcom": "ug", "b.com": "ug", "llb": "ug",
    "pg": "pg", "postgraduate": "pg", "post-graduate": "pg",
    "master": "pg", "masters": "pg", "mtech": "pg", "m.tech": "pg", "me": "pg",
    "msc": "pg", "m.sc": "pg", "ma": "pg", "m.a": "pg", "mba": "pg", "llm": "pg",
    "diploma": "diploma",
    "phd": "phd", "doctorate": "phd", "ph.d": "phd",
    "any": "any",
}


def normalise_education_level(raw: str) -> Optional[str]:
    """
    Map common student phrasing to the canonical education level token.

    Returns the canonical token ("5th"…"phd", "any") or None if the input
    is empty/unparseable — never guesses.
    """
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower().replace("-", "").replace("_", " ").replace(".", "")
    key = " ".join(key.split())  # collapse whitespace
    return _EDUCATION_ALIASES.get(key) or _EDUCATION_ALIASES.get(key.replace(" ", ""))


# ---------------------------------------------------------------------------
# Criterion evaluator protocol
# ---------------------------------------------------------------------------

class EligibilityResult:
    """Result of evaluating one criterion against one student."""
    __slots__ = ("status", "criterion", "required", "provided", "note")

    def __init__(
        self,
        status: str,
        criterion: str,
        required: Optional[str] = None,
        provided: Optional[str] = None,
        note: Optional[str] = None,
    ) -> None:
        self.status = status      # "met" | "not_met" | "unknown"
        self.criterion = criterion
        self.required = required
        self.provided = provided
        self.note = note

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"criterion": self.criterion, "required": self.required}
        if self.provided is not None:
            out["provided"] = self.provided
        if self.note:
            out["note"] = self.note
        return out


def _eval_education(criterion: Criterion, student: dict[str, Any]) -> EligibilityResult:
    raw = student.get("education_level")
    required = f"One of: {criterion.value}"
    if raw is None:
        return EligibilityResult("unknown", "education_level", required=required, note="Not provided by student")
    provided = normalise_education_level(str(raw))
    if provided is None:
        return EligibilityResult("unknown", "education_level", required=required, note="Could not understand provided level")
    allowed = {str(v).lower() for v in (criterion.value or [])}
    if provided.lower() in allowed or "any" in allowed:
        return EligibilityResult("met", "education_level", required=required, provided=str(raw))
    return EligibilityResult("not_met", "education_level", required=required, provided=str(raw), note="Education level does not match scheme requirement")


def _eval_state(criterion: Criterion, student: dict[str, Any]) -> EligibilityResult:
    required = str(criterion.value)
    raw = student.get("state")
    if raw is None:
        return EligibilityResult("unknown", "state", required=required, note="Not provided by student")
    if str(raw).strip().lower() == required.strip().lower():
        return EligibilityResult("met", "state", required=required, provided=str(raw))
    return EligibilityResult("not_met", "state", required=required, provided=str(raw), note="State does not match; this is a state-specific scheme")


def _eval_caste(criterion: Criterion, student: dict[str, Any]) -> EligibilityResult:
    required = f"One of: {criterion.value}"
    raw = student.get("caste_category")
    if raw is None:
        return EligibilityResult("unknown", "caste_category", required=required, note="Not provided by student")
    allowed = {str(v).upper() for v in (criterion.value or [])}
    if str(raw).upper() in allowed or "ANY" in allowed:
        return EligibilityResult("met", "caste_category", required=required, provided=str(raw))
    return EligibilityResult("not_met", "caste_category", required=required, provided=str(raw), note="Caste category does not meet scheme requirement")


def _eval_min_percentage(criterion: Criterion, student: dict[str, Any]) -> EligibilityResult:
    threshold = float(criterion.value)
    required = f">= {threshold}%"
    raw = student.get("percentage")
    if raw is None:
        return EligibilityResult("unknown", "percentage", required=required, note="Not provided by student")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return EligibilityResult("unknown", "percentage", required=required, note="Could not parse provided percentage")
    if val >= threshold:
        return EligibilityResult("met", "percentage", required=required, provided=f"{val}%")
    return EligibilityResult("not_met", "percentage", required=required, provided=f"{val}%", note="Academic percentage is below the minimum required")


def _eval_income(criterion: Criterion, student: dict[str, Any]) -> EligibilityResult:
    max_income = float(criterion.value)
    required = f"<= ₹{max_income:,.0f}"
    raw = student.get("annual_family_income")
    if raw is None:
        return EligibilityResult("unknown", "annual_family_income", required=required, note="Not provided by student")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return EligibilityResult("unknown", "annual_family_income", required=required, note="Could not parse provided income")
    if val <= max_income:
        return EligibilityResult("met", "annual_family_income", required=required, provided=f"₹{val:,.0f}")
    return EligibilityResult("not_met", "annual_family_income", required=required, provided=f"₹{val:,.0f}", note="Family income exceeds the maximum allowed")


def _eval_gender(criterion: Criterion, student: dict[str, Any]) -> EligibilityResult:
    required = str(criterion.value)
    raw = student.get("gender")
    if raw is None:
        return EligibilityResult("unknown", "gender", required=required, note="Not provided by student")
    if str(raw).strip().lower() == required.strip().lower():
        return EligibilityResult("met", "gender", required=required, provided=str(raw))
    return EligibilityResult("not_met", "gender", required=required, provided=str(raw), note="Gender does not meet scheme requirement")


def _eval_disability(criterion: Criterion, student: dict[str, Any]) -> EligibilityResult:
    required = "Disability certificate required" if criterion.value else "No disability certificate required"
    raw = student.get("disability")
    if raw is None:
        return EligibilityResult("unknown", "disability_required", required=required, note="Not provided by student")
    has_disability = bool(raw)
    if bool(criterion.value) is has_disability:
        return EligibilityResult("met", "disability_required", required=required, provided=str(has_disability))
    return EligibilityResult("not_met", "disability_required", required=required, provided=str(has_disability), note="Disability requirement not met")


# ---------------------------------------------------------------------------
# Registry — maps criterion field name → evaluator
# ---------------------------------------------------------------------------

ELIGIBILITY_REGISTRY: dict[str, Any] = {
    "education_level": _eval_education,
    "state": _eval_state,
    "caste_category": _eval_caste,
    "min_percentage": _eval_min_percentage,
    "annual_family_income": _eval_income,
    "gender": _eval_gender,
    "disability_required": _eval_disability,
}

# Eligibility disclaimer — always included in results
ELIGIBILITY_DISCLAIMER = (
    "This is guidance only, not official approval. Eligibility is determined "
    "solely by the scheme's administering authority. Please verify all criteria "
    "on the official portal before applying."
)


# ---------------------------------------------------------------------------
# High-level evaluator
# ---------------------------------------------------------------------------

def evaluate_scheme(
    criterion_list: list[Criterion],
    student_info: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate all criteria in a scheme's criterion_list against student_info.

    Returns a dict with:
      status:   potential_match | not_eligible_based_on_provided_information
                | more_information_needed
      satisfied:  [dict] — met criteria
      unsatisfied: [dict] — not_met criteria
      unknown:     [dict] — unknown criteria
      disclaimer:  str
    """
    satisfied: list[dict[str, Any]] = []
    unsatisfied: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []

    for criterion in criterion_list:
        evaluator = ELIGIBILITY_REGISTRY.get(criterion.field)
        if evaluator is None:
            unknown.append({
                "criterion": criterion.field,
                "required": f"{criterion.operator} {criterion.value}",
                "note": "No evaluator registered for this criterion",
            })
            continue

        result = evaluator(criterion, student_info)
        bucket = {"met": satisfied, "not_met": unsatisfied, "unknown": unknown}
        bucket[result.status].append(result.as_dict())

    if unsatisfied:
        status = "not_eligible_based_on_provided_information"
    elif unknown:
        status = "more_information_needed"
    else:
        status = "potential_match"

    return {
        "status": status,
        "satisfied_criteria": satisfied,
        "unsatisfied_criteria": unsatisfied,
        "unknown_criteria": unknown,
        "disclaimer": ELIGIBILITY_DISCLAIMER,
    }