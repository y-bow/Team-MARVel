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
    # Academic year, e.g. "2024-25"
    academic_year: Optional[str] = None
    
    # Education level(s) that qualify, e.g. ["10th", "12th", "UG", "PG"].
    education_levels: Optional[list[str]] = None

    # Specific courses eligible, e.g. ["B.Tech", "MBBS"]
    eligible_courses: Optional[list[str]] = None

    # Type of institutions, e.g. ["Government", "Private", "Aided"]
    institution_types: Optional[list[str]] = None

    # Domicile requirement, e.g. "Maharashtra"
    domicile: Optional[str] = None

    # Indian state name (where applicable).
    state: Optional[str] = None

    # Caste/reservation category.
    caste_categories: Optional[list[str]] = None

    # Minimum academic percentage required (0–100).
    min_percentage: Optional[float] = None

    # Details about merit requirements, e.g. "Top 1% of board"
    merit_requirements: Optional[str] = None

    # Maximum annual family income in INR.
    annual_family_income_max: Optional[float] = None

    # Gender restriction.
    gender: Optional[str] = None

    # Whether a disability certificate is required.
    disability_required: Optional[bool] = None

    # Evidence for criteria, mapping field name to source/page reference
    evidence: dict[str, str] = field(default_factory=dict)

    # Any additional free-form criteria notes.
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Scheme record — canonical shape
# ---------------------------------------------------------------------------

@dataclass
class SchemeRecord:
    """
    A single government/private scheme or opportunity.
    """

    id: str
    name: str
    description: str
    criteria: EligibilityCriteria
    
    # Provider and administering authority
    provider: Optional[str] = None
    administering_authority: Optional[str] = None

    # Award details
    award_amount: Optional[str] = None
    award_duration: Optional[str] = None
    renewal_conditions: Optional[str] = None

    documents: list[str] = field(default_factory=list)
    application_steps: list[str] = field(default_factory=list)

    # Dates
    opening_date: Optional[str] = None
    deadline: Optional[str] = None

    # URLs
    source_url: Optional[str] = None
    source_document_urls: list[str] = field(default_factory=list)

    # Status & verification
    verified: bool = False
    last_checked: Optional[str] = None
    source_updated_date: Optional[str] = None
    
    # Record status (e.g., 'draft', 'verified', 'expired', 'needs_review')
    record_status: str = "draft"

    tags: list[str] = field(default_factory=list)
    description_snippet: Optional[str] = None


# ---------------------------------------------------------------------------
# Factory: build a SchemeRecord from a raw JSON dict
# ---------------------------------------------------------------------------

def scheme_from_dict(data: dict[str, Any]) -> SchemeRecord:
    """
    Build a SchemeRecord from a raw dict (as parsed from JSON).
    """
    for required in ("id", "name", "description"):
        if not data.get(required):
            raise ValueError(
                f"Scheme record is missing required field '{required}': {data.get('id', 'unknown')}"
            )

    raw_criteria = data.get("criteria") or {}
    criteria = EligibilityCriteria(
        academic_year=raw_criteria.get("academic_year"),
        education_levels=raw_criteria.get("education_levels") or raw_criteria.get("education_level"),
        eligible_courses=raw_criteria.get("eligible_courses"),
        institution_types=raw_criteria.get("institution_types"),
        domicile=raw_criteria.get("domicile"),
        state=raw_criteria.get("state"),
        caste_categories=raw_criteria.get("caste_categories") or raw_criteria.get("caste_category"),
        min_percentage=raw_criteria.get("min_percentage"),
        merit_requirements=raw_criteria.get("merit_requirements"),
        annual_family_income_max=raw_criteria.get("annual_family_income_max"),
        gender=raw_criteria.get("gender"),
        disability_required=raw_criteria.get("disability_required"),
        evidence=raw_criteria.get("evidence") or {},
        notes=raw_criteria.get("notes"),
    )

    description = data["description"]
    snippet = data.get("description_snippet") or (
        description[:200] + "…" if len(description) > 200 else description
    )

    return SchemeRecord(
        id=data["id"],
        name=data["name"],
        provider=data.get("provider"),
        administering_authority=data.get("administering_authority"),
        description=description,
        criteria=criteria,
        award_amount=data.get("award_amount"),
        award_duration=data.get("award_duration"),
        renewal_conditions=data.get("renewal_conditions"),
        documents=data.get("documents") or [],
        application_steps=data.get("application_steps") or [],
        opening_date=data.get("opening_date"),
        deadline=data.get("deadline"),
        source_url=data.get("source_url"),
        source_document_urls=data.get("source_document_urls") or [],
        verified=bool(data.get("verified", False)),
        last_checked=data.get("last_checked"),
        source_updated_date=data.get("source_updated_date"),
        record_status=data.get("record_status", "draft"),
        tags=data.get("tags") or [],
        description_snippet=snippet,
    )
