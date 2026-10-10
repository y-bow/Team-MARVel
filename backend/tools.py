"""
tools.py — EduSaarthi AI tool functions.

Each function is a pure Python callable that:
  1. Validates its inputs.
  2. Calls the repository (never touches JSON directly).
  3. Returns a JSON-serializable dict.
  4. Handles missing records and edge cases with structured, honest responses.

Rules enforced here:
  - Missing info is NEVER proof of eligibility.
  - NEVER invent criteria, documents, or deadlines absent from the data.
  - NEVER claim an application was submitted.
  - NEVER scrape websites.
  - Stale / unverified deadlines are always flagged.
  - All status values are one of the defined constants.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from backend.repository import BaseRepository
from backend.schemas import SchemeRecord

# ---------------------------------------------------------------------------
# Eligibility status constants
# ---------------------------------------------------------------------------

STATUS_POTENTIAL_MATCH = "potential_match"
STATUS_NOT_ELIGIBLE = "not_eligible_based_on_provided_information"
STATUS_MORE_INFO_NEEDED = "more_information_needed"

# Deadline status constants
DEADLINE_CURRENT = "current"
DEADLINE_PAST = "past"
DEADLINE_UNKNOWN = "unknown"
DEADLINE_STALE = "stale"
DEADLINE_UNVERIFIED = "unverified"

# Eligibility disclaimer — always included
ELIGIBILITY_DISCLAIMER = (
    "This is guidance only, not official approval. Eligibility is determined "
    "solely by the scheme's administering authority. Please verify all criteria "
    "on the official portal before applying."
)

# Action plan disclaimer
ACTION_PLAN_DISCLAIMER = (
    "Steps marked 'requires_user_verification' must be confirmed by the student "
    "on the official portal. This plan is a guide only — EduSaarthi AI does not "
    "submit applications or guarantee outcomes."
)

# Allowed education levels for input validation
VALID_EDUCATION_LEVELS = {
    "5th", "6th", "7th", "8th", "9th", "10th", "11th", "12th",
    "ug", "pg", "diploma", "phd", "any",
}

# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

def _validate_str(value: Any, name: str, max_len: int = 500) -> str:
    if not isinstance(value, str):
        raise ValueError(f"'{name}' must be a string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"'{name}' must not be empty")
    if len(stripped) > max_len:
        raise ValueError(f"'{name}' exceeds maximum length of {max_len} characters")
    return stripped


def _validate_optional_str(value: Any, name: str, max_len: int = 200) -> Optional[str]:
    if value is None or value == "":
        return None
    return _validate_str(value, name, max_len)


def _validate_scheme_id(scheme_id: Any) -> str:
    sid = _validate_str(scheme_id, "scheme_id", max_len=200)
    if not re.match(r"^[a-z0-9_-]+$", sid):
        raise ValueError(
            "scheme_id must contain only lowercase letters, digits, hyphens, "
            f"and underscores; got: {sid!r}"
        )
    return sid


def _error_response(code: str, message: str) -> dict[str, Any]:
    return {"error": True, "error_code": code, "message": message}


def _not_found(scheme_id: str) -> dict[str, Any]:
    return _error_response(
        "SCHEME_NOT_FOUND",
        f"No scheme found with id '{scheme_id}'. "
        "Use search_schemes to find valid scheme IDs.",
    )


# ---------------------------------------------------------------------------
# Tool 1: search_schemes
# ---------------------------------------------------------------------------

def search_schemes(
    repository: BaseRepository,
    query: str,
    education_level: Optional[str] = None,
    state: Optional[str] = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """
    Keyword search for schemes with optional structured filters.

    Returns up to max_results results.
    Returns {"results": []} when nothing matches — never None.
    """
    try:
        query = _validate_str(query, "query", max_len=500)
        education_level = _validate_optional_str(education_level, "education_level", 50)
        state = _validate_optional_str(state, "state", 100)
    except ValueError as exc:
        return _error_response("INVALID_INPUT", str(exc))

    if education_level and education_level.lower() not in VALID_EDUCATION_LEVELS:
        return _error_response(
            "INVALID_EDUCATION_LEVEL",
            f"education_level must be one of: {sorted(VALID_EDUCATION_LEVELS)}. "
            f"Got: {education_level!r}",
        )

    # Clamp max_results defensively
    max_results = max(1, min(max_results, 50))

    schemes = repository.search(
        query=query,
        education_level=education_level,
        state=state,
        max_results=max_results,
    )

    results = [
        {
            "id": s.id,
            "name": s.name,
            "description_snippet": s.description_snippet,
            "education_levels": s.criteria.education_levels,
            "state": s.criteria.state or "All India",
            "source_url": s.source_url,
            "verified": s.verified,
            "tags": s.tags,
        }
        for s in schemes
    ]

    return {
        "query": query,
        "filters_applied": {
            "education_level": education_level,
            "state": state,
        },
        "result_count": len(results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Tool 2: check_eligibility
# ---------------------------------------------------------------------------

def check_eligibility(
    repository: BaseRepository,
    scheme_id: str,
    student_info: dict[str, Any],
) -> dict[str, Any]:
    """
    Deterministic eligibility check against structured criteria.

    Uses only criteria present in the data — never invents criteria.
    Missing student info is NEVER treated as proof of eligibility.

    student_info keys (all optional):
      education_level: str
      state: str
      caste_category: str
      percentage: float
      annual_family_income: float
      gender: str
      disability: bool
    """
    try:
        scheme_id = _validate_scheme_id(scheme_id)
    except ValueError as exc:
        return _error_response("INVALID_INPUT", str(exc))

    if not isinstance(student_info, dict):
        return _error_response(
            "INVALID_INPUT", "student_info must be an object/dict"
        )

    scheme = repository.get_by_id(scheme_id)
    if scheme is None:
        return _not_found(scheme_id)

    c = scheme.criteria
    satisfied: list[dict[str, str]] = []
    unsatisfied: list[dict[str, str]] = []
    unknown: list[dict[str, str]] = []

    # --- education_level ---
    if c.education_levels and "any" not in [lv.lower() for lv in c.education_levels]:
        student_edu = student_info.get("education_level")
        if student_edu is None:
            unknown.append({
                "criterion": "education_level",
                "required": f"One of: {c.education_levels}",
                "provided": None,
                "note": "Not provided by student",
            })
        elif student_edu.lower().strip() in [lv.lower() for lv in c.education_levels]:
            satisfied.append({
                "criterion": "education_level",
                "required": f"One of: {c.education_levels}",
                "provided": student_edu,
            })
        else:
            unsatisfied.append({
                "criterion": "education_level",
                "required": f"One of: {c.education_levels}",
                "provided": student_edu,
                "note": "Education level does not match scheme requirement",
            })

    # --- state ---
    if c.state:
        student_state = student_info.get("state")
        if student_state is None:
            unknown.append({
                "criterion": "state",
                "required": c.state,
                "provided": None,
                "note": "Not provided by student",
            })
        elif student_state.lower().strip() == c.state.lower().strip():
            satisfied.append({
                "criterion": "state",
                "required": c.state,
                "provided": student_state,
            })
        else:
            unsatisfied.append({
                "criterion": "state",
                "required": c.state,
                "provided": student_state,
                "note": "State does not match; this is a state-specific scheme",
            })

    # --- caste_category ---
    if c.caste_categories and "any" not in [cc.lower() for cc in c.caste_categories]:
        student_caste = student_info.get("caste_category")
        if student_caste is None:
            unknown.append({
                "criterion": "caste_category",
                "required": f"One of: {c.caste_categories}",
                "provided": None,
                "note": "Not provided by student",
            })
        elif student_caste.upper().strip() in [cc.upper() for cc in c.caste_categories]:
            satisfied.append({
                "criterion": "caste_category",
                "required": f"One of: {c.caste_categories}",
                "provided": student_caste,
            })
        else:
            unsatisfied.append({
                "criterion": "caste_category",
                "required": f"One of: {c.caste_categories}",
                "provided": student_caste,
                "note": "Caste category does not meet scheme requirement",
            })

    # --- min_percentage ---
    if c.min_percentage is not None:
        student_pct = student_info.get("percentage")
        if student_pct is None:
            unknown.append({
                "criterion": "percentage",
                "required": f">= {c.min_percentage}%",
                "provided": None,
                "note": "Not provided by student",
            })
        else:
            try:
                pct_val = float(student_pct)
            except (TypeError, ValueError):
                unknown.append({
                    "criterion": "percentage",
                    "required": f">= {c.min_percentage}%",
                    "provided": student_pct,
                    "note": "Could not parse provided percentage",
                })
            else:
                if pct_val >= c.min_percentage:
                    satisfied.append({
                        "criterion": "percentage",
                        "required": f">= {c.min_percentage}%",
                        "provided": f"{pct_val}%",
                    })
                else:
                    unsatisfied.append({
                        "criterion": "percentage",
                        "required": f">= {c.min_percentage}%",
                        "provided": f"{pct_val}%",
                        "note": "Academic percentage is below the minimum required",
                    })

    # --- annual_family_income ---
    if c.annual_family_income_max is not None:
        student_income = student_info.get("annual_family_income")
        if student_income is None:
            unknown.append({
                "criterion": "annual_family_income",
                "required": f"<= ₹{c.annual_family_income_max:,.0f}",
                "provided": None,
                "note": "Not provided by student",
            })
        else:
            try:
                income_val = float(student_income)
            except (TypeError, ValueError):
                unknown.append({
                    "criterion": "annual_family_income",
                    "required": f"<= ₹{c.annual_family_income_max:,.0f}",
                    "provided": student_income,
                    "note": "Could not parse provided income",
                })
            else:
                if income_val <= c.annual_family_income_max:
                    satisfied.append({
                        "criterion": "annual_family_income",
                        "required": f"<= ₹{c.annual_family_income_max:,.0f}",
                        "provided": f"₹{income_val:,.0f}",
                    })
                else:
                    unsatisfied.append({
                        "criterion": "annual_family_income",
                        "required": f"<= ₹{c.annual_family_income_max:,.0f}",
                        "provided": f"₹{income_val:,.0f}",
                        "note": "Family income exceeds the maximum allowed",
                    })

    # --- gender ---
    if c.gender and c.gender.lower() != "any":
        student_gender = student_info.get("gender")
        if student_gender is None:
            unknown.append({
                "criterion": "gender",
                "required": c.gender,
                "provided": None,
                "note": "Not provided by student",
            })
        elif student_gender.lower().strip() == c.gender.lower().strip():
            satisfied.append({
                "criterion": "gender",
                "required": c.gender,
                "provided": student_gender,
            })
        else:
            unsatisfied.append({
                "criterion": "gender",
                "required": c.gender,
                "provided": student_gender,
                "note": "Gender does not meet scheme requirement",
            })

    # Determine overall status
    if unsatisfied:
        status = STATUS_NOT_ELIGIBLE
    elif unknown:
        status = STATUS_MORE_INFO_NEEDED
    else:
        status = STATUS_POTENTIAL_MATCH

    return {
        "scheme_id": scheme.id,
        "scheme_name": scheme.name,
        "status": status,
        "satisfied_criteria": satisfied,
        "unsatisfied_criteria": unsatisfied,
        "unknown_criteria": unknown,
        "additional_notes": c.notes,
        "disclaimer": ELIGIBILITY_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Tool 3: get_requirements
# ---------------------------------------------------------------------------

def get_requirements(
    repository: BaseRepository,
    scheme_id: str,
) -> dict[str, Any]:
    """
    Return documents, application steps, official URLs, and verification metadata.

    Distinguishes 'information missing from database' (information_complete=false)
    from 'empty requirements list' (documents=[], steps=[]).
    NEVER invents documents.
    """
    try:
        scheme_id = _validate_scheme_id(scheme_id)
    except ValueError as exc:
        return _error_response("INVALID_INPUT", str(exc))

    req = repository.get_requirements(scheme_id)
    if req is None:
        return _not_found(scheme_id)

    warnings: list[str] = []
    if not req.get("source_url"):
        warnings.append(
            "Official source URL is not available in the knowledge base. "
            "Please search for this scheme on scholarships.gov.in or the official website."
        )
    if not req.get("verified"):
        warnings.append(
            "This scheme record has not been independently verified. "
            "Confirm all requirements on the official portal."
        )
    if not req.get("last_checked"):
        warnings.append(
            "This record has never been checked against the official source. "
            "Requirements may be outdated."
        )

    return {**req, "warnings": warnings}


# ---------------------------------------------------------------------------
# Tool 4: verify_deadline
# ---------------------------------------------------------------------------

def verify_deadline(
    repository: BaseRepository,
    scheme_id: str,
    stale_days: int = 30,
) -> dict[str, Any]:
    """
    Return the recorded deadline, source, verification status, and last_checked.

    NEVER calls a deadline 'current' unless verified=True and last_checked
    is within stale_days days.
    NEVER scrapes websites.
    """
    try:
        scheme_id = _validate_scheme_id(scheme_id)
    except ValueError as exc:
        return _error_response("INVALID_INPUT", str(exc))

    scheme = repository.get_by_id(scheme_id)
    if scheme is None:
        return _not_found(scheme_id)

    today = date.today()
    deadline_status: str
    warning: str

    if not scheme.deadline:
        deadline_status = DEADLINE_UNKNOWN
        warning = (
            "No deadline is recorded for this scheme in the knowledge base. "
            "Check the official portal for the current deadline."
        )
    else:
        try:
            dl_date = date.fromisoformat(scheme.deadline)
        except ValueError:
            deadline_status = DEADLINE_UNKNOWN
            warning = (
                f"Deadline value '{scheme.deadline}' could not be parsed as a date. "
                "Check the official portal."
            )
        else:
            if dl_date < today:
                deadline_status = DEADLINE_PAST
                warning = (
                    f"The recorded deadline ({scheme.deadline}) has already passed. "
                    "Check the official portal for a renewed or extended deadline."
                )
            elif not scheme.verified:
                deadline_status = DEADLINE_UNVERIFIED
                warning = (
                    "This deadline has NOT been verified against an authoritative source. "
                    "Treat it as approximate and confirm on the official portal."
                )
            elif not scheme.last_checked:
                deadline_status = DEADLINE_UNVERIFIED
                warning = (
                    "The deadline source has never been checked. "
                    "Confirm on the official portal."
                )
            else:
                try:
                    checked_date = date.fromisoformat(scheme.last_checked)
                    days_since = (today - checked_date).days
                except ValueError:
                    days_since = stale_days + 1

                if days_since > stale_days:
                    deadline_status = DEADLINE_STALE
                    warning = (
                        f"This record was last checked {days_since} day(s) ago "
                        f"(threshold: {stale_days} days). "
                        "The deadline may have changed. Confirm on the official portal."
                    )
                else:
                    deadline_status = DEADLINE_CURRENT
                    warning = (
                        f"Deadline verified against official source on {scheme.last_checked}."
                    )

    return {
        "scheme_id": scheme.id,
        "scheme_name": scheme.name,
        "deadline": scheme.deadline,
        "deadline_status": deadline_status,
        "source_url": scheme.source_url,
        "verified": scheme.verified,
        "last_checked": scheme.last_checked,
        "warning": warning,
    }


# ---------------------------------------------------------------------------
# Tool 5: create_action_plan
# ---------------------------------------------------------------------------

def create_action_plan(
    goal: str,
    scheme_ids: list[str],
    eligibility_results: list[dict[str, Any]],
    missing_info: list[str],
) -> dict[str, Any]:
    """
    Create a structured, source-linked action plan.

    Steps requiring student verification are explicitly marked.
    NEVER claims an application was submitted.
    """
    try:
        goal = _validate_str(goal, "goal", max_len=1000)
    except ValueError as exc:
        return _error_response("INVALID_INPUT", str(exc))

    if not isinstance(scheme_ids, list):
        return _error_response("INVALID_INPUT", "scheme_ids must be a list")
    if not isinstance(eligibility_results, list):
        return _error_response("INVALID_INPUT", "eligibility_results must be a list")
    if not isinstance(missing_info, list):
        return _error_response("INVALID_INPUT", "missing_info must be a list")

    steps: list[dict[str, Any]] = []

    # Step 0: Gather missing information first
    if missing_info:
        for item in missing_info[:10]:  # cap
            if isinstance(item, str) and item.strip():
                steps.append({
                    "title": f"Gather information: {item.strip()}",
                    "description": (
                        f"You need to provide '{item.strip()}' before eligibility "
                        "can be fully assessed. Collect or look up this information."
                    ),
                    "action_type": "gather_document",
                    "scheme_id": None,
                    "requires_user_verification": False,
                    "completed": False,
                })

    # Steps derived from eligibility results
    for result in eligibility_results[:10]:  # cap
        if not isinstance(result, dict):
            continue
        sid = result.get("scheme_id", "")
        sname = result.get("scheme_name", sid)
        status = result.get("status", "")

        if status == STATUS_NOT_ELIGIBLE:
            steps.append({
                "title": f"Review ineligibility for: {sname}",
                "description": (
                    f"You do not currently meet one or more criteria for '{sname}'. "
                    "Review the unsatisfied criteria and confirm on the official portal "
                    "whether exceptions or appeals are possible."
                ),
                "action_type": "verify",
                "scheme_id": sid,
                "requires_user_verification": True,
                "completed": False,
            })

        elif status == STATUS_MORE_INFO_NEEDED:
            unknowns = result.get("unknown_criteria", [])
            unknown_names = [u.get("criterion", "") for u in unknowns if isinstance(u, dict)]
            steps.append({
                "title": f"Provide missing information for: {sname}",
                "description": (
                    f"The following details are needed to assess your eligibility for '{sname}': "
                    f"{', '.join(unknown_names)}. "
                    "Gather these and re-run the eligibility check."
                ),
                "action_type": "gather_document",
                "scheme_id": sid,
                "requires_user_verification": False,
                "completed": False,
            })

        elif status == STATUS_POTENTIAL_MATCH:
            steps.append({
                "title": f"Verify eligibility on official portal: {sname}",
                "description": (
                    f"Based on the information you provided, you appear to meet the "
                    f"criteria for '{sname}'. Confirm your eligibility on the official "
                    f"portal and review all requirements before applying."
                ),
                "action_type": "verify",
                "scheme_id": sid,
                "requires_user_verification": True,
                "completed": False,
            })
            steps.append({
                "title": f"Prepare documents and apply: {sname}",
                "description": (
                    f"Gather all required documents for '{sname}' and complete "
                    "the application on the official portal. "
                    "Use get_requirements to see the full document list."
                ),
                "action_type": "apply",
                "scheme_id": sid,
                "requires_user_verification": True,
                "completed": False,
            })

    # Always end with a research step
    if not steps:
        steps.append({
            "title": "Search for matching schemes",
            "description": (
                "Start by searching for schemes matching your profile using the "
                "search_schemes tool. Provide your education level, state, and "
                "category to narrow results."
            ),
            "action_type": "research",
            "scheme_id": None,
            "requires_user_verification": False,
            "completed": False,
        })

    steps.append({
        "title": "Keep track of deadlines",
        "description": (
            "Use the verify_deadline tool to check the deadline for each scheme "
            "you plan to apply for. Set personal reminders well before the closing date."
        ),
        "action_type": "verify",
        "scheme_id": None,
        "requires_user_verification": True,
        "completed": False,
    })

    return {
        "goal": goal,
        "scheme_ids": scheme_ids,
        "steps": steps,
        "disclaimer": ACTION_PLAN_DISCLAIMER,
    }
