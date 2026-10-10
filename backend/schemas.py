"""
schemas.py — EduSaarthi AI data model.

Defines the canonical shape of a scheme record and related types.
All fields are documented. Optional fields are typed as Optional[X].

IMPORTANT FOR TEAMMATES:
  This schema is the shared contract between the knowledge-base JSON
  and the backend tools. If you add or rename fields in schemes.json,
  update this file accordingly and notify the backend maintainer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Eligibility criteria
# ---------------------------------------------------------------------------

@dataclass
class EligibilityCriteria:
    """
    Structured eligibility criteria for a scheme.

    All fields are Optional — None means "not specified / no restriction".
    Tools MUST NOT invent criteria absent from the source data.
    """
    # Education level(s) that qualify, e.g. ["10th", "12th", "UG", "PG"].
    # None or ["any"] means no restriction.
    education_levels: Optional[list[str]] = None

    # Indian state name, e.g. "Maharashtra". None means all-India.
    state: Optional[str] = None

    # Caste/reservation category. None or ["any"] means unrestricted.
    caste_categories: Optional[list[str]] = None

    # Minimum academic percentage required (0–100). None means no restriction.
    min_percentage: Optional[float] = None

    # Maximum annual family income in INR. None means no restriction.
    annual_family_income_max: Optional[float] = None

    # Gender restriction. None or "any" means unrestricted.
    gender: Optional[str] = None

    # Whether a disability certificate is required (True) / not required (False)
    # or not specified (None).
    disability_required: Optional[bool] = None

    # Any additional free-form criteria notes sourced from the data.
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Scheme record — canonical shape
# ---------------------------------------------------------------------------

@dataclass
class SchemeRecord:
    """
    A single government/private scheme or opportunity.

    Fields map 1-to-1 to the JSON knowledge base. Source metadata is
    stored alongside the claims it supports (source_url, verified,
    last_checked) so downstream tools can propagate provenance.
    """

    # Unique slug identifier, e.g. "nsp-pre-matric-2024"
    id: str

    # Human-readable scheme name
    name: str

    # Full description of the scheme (may be multi-sentence)
    description: str

    # Structured eligibility criteria
    criteria: EligibilityCriteria

    # List of required documents (strings). Empty list is valid.
    documents: list[str] = field(default_factory=list)

    # Ordered application steps (strings). Empty list is valid.
    application_steps: list[str] = field(default_factory=list)

    # Application deadline as ISO 8601 date string, e.g. "2024-03-31".
    # None means unknown / not published.
    deadline: Optional[str] = None

    # Official portal or application URL.
    # None means not available in the knowledge base.
    source_url: Optional[str] = None

    # True if the record has been verified against an authoritative source.
    verified: bool = False

    # ISO 8601 date when this record was last checked against source.
    # None means never checked.
    last_checked: Optional[str] = None

    # Searchable tags, e.g. ["scholarship", "merit", "central"].
    tags: list[str] = field(default_factory=list)

    # Short snippet used in search results (auto-derived if absent)
    description_snippet: Optional[str] = None


# ---------------------------------------------------------------------------
# Factory: build a SchemeRecord from a raw JSON dict
# ---------------------------------------------------------------------------

def scheme_from_dict(data: dict[str, Any]) -> SchemeRecord:
    """
    Build a SchemeRecord from a raw dict (as parsed from JSON).

    Unknown fields are silently ignored so the schema can evolve.
    Missing optional fields default to None / empty list.
    Raises ValueError if required fields (id, name, description) are absent.
    """
    for required in ("id", "name", "description"):
        if not data.get(required):
            raise ValueError(
                f"Scheme record is missing required field '{required}': {data!r}"
            )

    raw_criteria = data.get("criteria") or {}
    criteria = EligibilityCriteria(
        education_levels=raw_criteria.get("education_levels") or raw_criteria.get("education_level"),
        state=raw_criteria.get("state"),
        caste_categories=raw_criteria.get("caste_categories") or raw_criteria.get("caste_category"),
        min_percentage=raw_criteria.get("min_percentage"),
        annual_family_income_max=raw_criteria.get("annual_family_income_max"),
        gender=raw_criteria.get("gender"),
        disability_required=raw_criteria.get("disability_required"),
        notes=raw_criteria.get("notes"),
    )

    description = data["description"]
    snippet = data.get("description_snippet") or (
        description[:200] + "…" if len(description) > 200 else description
    )

    return SchemeRecord(
        id=data["id"],
        name=data["name"],
        description=description,
        criteria=criteria,
        documents=data.get("documents") or [],
        application_steps=data.get("application_steps") or [],
        deadline=data.get("deadline"),
        source_url=data.get("source_url"),
        verified=bool(data.get("verified", False)),
        last_checked=data.get("last_checked"),
        tags=data.get("tags") or [],
        description_snippet=snippet,
    )
