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

import datetime
import re
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
# Schema v2 types — typed criteria and provenance
# ---------------------------------------------------------------------------

@dataclass
class Criterion:
    """
    One typed eligibility criterion (schema v2).

    field     — canonical criterion name from CRITERION_FIELDS.
    operator  — one of CRITERION_OPERATORS: "in" (value in allowed set),
                "eq", "gte", "lte".
    value     — the required value; type depends on field.
    source_ref — optional id of the evidence item supporting this criterion.
    """
    field: str
    operator: str = "eq"
    value: Any = None
    source_ref: Optional[str] = None


@dataclass
class EvidenceItem:
    """
    Verbatim evidence from an official source (schema v2).

    quote must be copied from the source document — never model-generated.
    """
    id: str
    field: str
    quote: str
    checked_at: Optional[str] = None


@dataclass
class ApplicationWindow:
    """Application window dates (ISO 8601) when known; None = unknown."""
    opens: Optional[str] = None
    closes: Optional[str] = None


# Criterion names the eligibility engine understands. Validation rejects
# unknown names so criteria can never be silently ignored.
CRITERION_FIELDS = {
    "education_level",
    "state",
    "caste_category",
    "min_percentage",
    "annual_family_income",
    "gender",
    "disability_required",
}

CRITERION_OPERATORS = {"in", "eq", "gte", "lte"}

# Evidence chunk types — each chunk is a retrieval unit.
CHUNK_TYPES = {"criteria", "documents", "steps", "deadline", "evidence", "summary"}


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

    # --- schema v2 fields (None / empty when the source record predates v2) ---

    # Academic cycle the record applies to, e.g. "2026-27". None = unknown.
    academic_year: Optional[str] = None

    # Application window; both dates None when unknown.
    application_window: ApplicationWindow = field(default_factory=ApplicationWindow)

    # Typed eligibility criteria (schema v2). Populated from v2 "criteria"
    # lists or derived from the v1 flat criteria block.
    criterion_list: list[Criterion] = field(default_factory=list)

    # Verbatim source evidence supporting the record's claims. Empty means
    # evidence has not been captured yet — never treat empty as verified.
    evidence: list[EvidenceItem] = field(default_factory=list)

    # Provenance details beyond source_url.
    source_title: Optional[str] = None
    source_publisher: Optional[str] = None
    verification_method: Optional[str] = None


# ---------------------------------------------------------------------------
# Factories: build a SchemeRecord from a raw JSON dict (v1 or v2)
# ---------------------------------------------------------------------------

EVIDENCE_FIELDS = CRITERION_FIELDS | {
    "deadline",
    "documents",
    "application_steps",
    "description",
    "general",
}

_ID_RE = r"^[a-z0-9_-]+$"


def _is_v2(data: dict[str, Any]) -> bool:
    return isinstance(data.get("criteria"), list)


def _typed_from_flat(raw: dict[str, Any]) -> list[Criterion]:
    """Derive typed criteria from the v1 flat criteria block."""
    typed: list[Criterion] = []
    levels = raw.get("education_levels") or raw.get("education_level")
    if levels:
        typed.append(Criterion(field="education_level", operator="in", value=list(levels)))
    if raw.get("state"):
        typed.append(Criterion(field="state", operator="eq", value=raw["state"]))
    cats = raw.get("caste_categories") or raw.get("caste_category")
    if cats:
        typed.append(Criterion(field="caste_category", operator="in", value=list(cats)))
    if raw.get("min_percentage") is not None:
        typed.append(Criterion(
            field="min_percentage", operator="gte", value=float(raw["min_percentage"])
        ))
    if raw.get("annual_family_income_max") is not None:
        typed.append(Criterion(
            field="annual_family_income", operator="lte",
            value=float(raw["annual_family_income_max"]),
        ))
    if raw.get("gender") and str(raw["gender"]).lower() != "any":
        typed.append(Criterion(field="gender", operator="eq", value=raw["gender"]))
    if raw.get("disability_required") is not None:
        typed.append(Criterion(
            field="disability_required", operator="eq",
            value=bool(raw["disability_required"]),
        ))
    return typed


def _flat_from_typed(typed: list[Criterion], notes: Optional[str]) -> EligibilityCriteria:
    """Derive the legacy flat criteria block from typed criteria."""
    flat = EligibilityCriteria(notes=notes)
    for criterion in typed:
        if criterion.field == "education_level" and criterion.operator == "in":
            flat.education_levels = [str(v) for v in (criterion.value or [])]
        elif criterion.field == "state":
            flat.state = str(criterion.value) if criterion.value else None
        elif criterion.field == "caste_category" and criterion.operator == "in":
            flat.caste_categories = [str(v) for v in (criterion.value or [])]
        elif criterion.field == "min_percentage" and criterion.operator == "gte":
            flat.min_percentage = float(criterion.value)
        elif criterion.field == "annual_family_income" and criterion.operator == "lte":
            flat.annual_family_income_max = float(criterion.value)
        elif criterion.field == "gender":
            flat.gender = str(criterion.value) if criterion.value else None
        elif criterion.field == "disability_required":
            flat.disability_required = bool(criterion.value)
    return flat


def scheme_from_dict(data: dict[str, Any]) -> SchemeRecord:
    """
    Build a SchemeRecord from a raw dict (schema v1 or v2).

    Unknown fields are silently ignored so the schema can evolve.
    Missing optional fields default to None / empty list.
    Raises ValueError if required fields (id, name, description) are absent.
    """
    for required in ("id", "name", "description"):
        if not data.get(required):
            raise ValueError(
                f"Scheme record is missing required field '{required}': {data!r}"
            )

    notes = data.get("notes")
    if _is_v2(data):
        typed = [
            Criterion(
                field=item["field"],
                operator=item.get("operator", "eq"),
                value=item.get("value"),
                source_ref=item.get("source_ref"),
            )
            for item in data["criteria"]
            if isinstance(item, dict) and item.get("field")
        ]
        criteria = _flat_from_typed(typed, notes)

        documents = [
            (item.get("name") if isinstance(item, dict) else item)
            for item in (data.get("documents") or [])
        ]
        raw_steps = [s for s in (data.get("application_steps") or []) if s]
        if any(isinstance(s, dict) for s in raw_steps):
            raw_steps = sorted(
                (s for s in raw_steps if isinstance(s, dict)),
                key=lambda s: s.get("order", 0),
            )
            application_steps = [str(s.get("text") or "").strip() for s in raw_steps]
        else:
            application_steps = [str(s) for s in raw_steps]

        raw_deadline = data.get("deadline")
        if isinstance(raw_deadline, dict):
            deadline = raw_deadline.get("date") or None
        else:
            deadline = raw_deadline or None

        source = data.get("source") or {}
        source_url = source.get("url") or None
        last_checked = source.get("checked_at") or None
        evidence = [
            EvidenceItem(
                id=str(item.get("id") or ""),
                field=str(item.get("field") or ""),
                quote=str(item.get("quote") or ""),
                checked_at=item.get("checked_at"),
            )
            for item in (source.get("evidence") or [])
            if isinstance(item, dict)
        ]
        source_title = source.get("title") or None
        source_publisher = source.get("publisher") or None
        verification_method = source.get("verification_method") or None

        window = data.get("application_window") or {}
        application_window = ApplicationWindow(
            opens=window.get("opens") or None,
            closes=window.get("closes") or None,
        )
        academic_year = data.get("academic_year") or None
    else:
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
        typed = _typed_from_flat(raw_criteria)
        documents = list(data.get("documents") or [])
        application_steps = [str(s) for s in (data.get("application_steps") or [])]
        deadline = data.get("deadline") or None
        source_url = data.get("source_url") or None
        last_checked = data.get("last_checked") or None
        evidence = []
        source_title = None
        source_publisher = None
        verification_method = None
        application_window = ApplicationWindow()
        academic_year = None

    description = data["description"]
    snippet = data.get("description_snippet") or (
        description[:200] + "…" if len(description) > 200 else description
    )

    return SchemeRecord(
        id=data["id"],
        name=data["name"],
        description=description,
        criteria=criteria,
        documents=[d for d in documents if d],
        application_steps=[s for s in application_steps if s],
        deadline=deadline,
        source_url=source_url,
        verified=bool(data.get("verified", False)),
        last_checked=last_checked,
        tags=data.get("tags") or [],
        description_snippet=snippet,
        academic_year=academic_year,
        application_window=application_window,
        criterion_list=typed,
        evidence=evidence,
        source_title=source_title,
        source_publisher=source_publisher,
        verification_method=verification_method,
    )


# ---------------------------------------------------------------------------
# Validation — deterministic dataset rules (used by tests and tooling)
# ---------------------------------------------------------------------------

def _check_date(value: Any, label: str, errors: list[str], record_id: str) -> None:
    if value in (None, ""):
        return
    try:
        datetime.date.fromisoformat(str(value))
    except ValueError:
        errors.append(f"[{record_id}] {label} is not an ISO 8601 date: {value!r}")


def validate_record(data: dict[str, Any]) -> list[str]:
    """
    Return a list of validation errors for one raw record (empty = valid).

    Rules never invent facts: they only check internal consistency of the
    stored values (shape, types, date formats, provenance requirements).
    """
    errors: list[str] = []
    record_id = str(data.get("id") or "<missing-id>")

    for required in ("id", "name", "description"):
        if not data.get(required):
            errors.append(f"[{record_id}] missing required field '{required}'")

    rid = data.get("id")
    if rid and not re.match(_ID_RE, str(rid)):
        errors.append(f"[{record_id}] id must match {_ID_RE}: {rid!r}")

    source = data.get("source") or {}
    if not _is_v2(data) and not source:
        source = {
            "url": data.get("source_url"),
            "checked_at": data.get("last_checked"),
            "evidence": [],
        }

    url = source.get("url")
    if url and not str(url).startswith(("http://", "https://")):
        errors.append(f"[{record_id}] source url must be http(s): {url!r}")

    checked_at = source.get("checked_at")
    _check_date(checked_at, "source.checked_at", errors, record_id)
    if data.get("verified") and not checked_at:
        errors.append(
            f"[{record_id}] verified=true requires source.checked_at (verification date)"
        )

    raw_deadline = data.get("deadline")
    if isinstance(raw_deadline, dict):
        _check_date(raw_deadline.get("date"), "deadline.date", errors, record_id)
    else:
        _check_date(raw_deadline, "deadline", errors, record_id)

    window = data.get("application_window") or {}
    if isinstance(window, dict):
        _check_date(window.get("opens"), "application_window.opens", errors, record_id)
        _check_date(window.get("closes"), "application_window.closes", errors, record_id)

    raw_criteria = data.get("criteria") if _is_v2(data) else []
    for item in raw_criteria or []:
        if not isinstance(item, dict) or not item.get("field"):
            errors.append(f"[{record_id}] criteria entries need a 'field'")
            continue
        field = item["field"]
        operator = item.get("operator", "eq")
        if field not in CRITERION_FIELDS:
            errors.append(f"[{record_id}] unknown criterion field {field!r}")
        if operator not in CRITERION_OPERATORS:
            errors.append(f"[{record_id}] unknown operator {operator!r} for {field!r}")
        value = item.get("value")
        if operator == "in" and not isinstance(value, list):
            errors.append(f"[{record_id}] operator 'in' requires a list value: {field!r}")
        if operator in ("gte", "lte") and not isinstance(value, (int, float)):
            errors.append(f"[{record_id}] operator {operator!r} requires a number: {field!r}")
        if operator in ("eq", "in") and value is None:
            errors.append(f"[{record_id}] criterion {field!r} has no value")

    for item in (source.get("evidence") or []):
        if not isinstance(item, dict):
            errors.append(f"[{record_id}] evidence entries must be objects")
            continue
        for required in ("id", "field", "quote"):
            if not item.get(required):
                errors.append(f"[{record_id}] evidence item missing '{required}'")
        if item.get("field") and item["field"] not in EVIDENCE_FIELDS:
            errors.append(f"[{record_id}] evidence field unknown: {item['field']!r}")
        _check_date(item.get("checked_at"), "evidence.checked_at", errors, record_id)

    for entry in data.get("documents") or []:
        if isinstance(entry, dict) and not entry.get("name"):
            errors.append(f"[{record_id}] document entry missing 'name'")

    for entry in data.get("application_steps") or []:
        if isinstance(entry, dict) and not entry.get("text"):
            errors.append(f"[{record_id}] application step missing 'text'")

    return errors


def validate_dataset(raw: Any) -> list[str]:
    """
    Validate a full knowledge-base document (v1 JSON array or v2 object).

    Returns all errors found (empty list = valid). Duplicate ids are errors.
    """
    if isinstance(raw, dict):
        records = raw.get("schemes")
        if not isinstance(records, list):
            return ["dataset object must contain a 'schemes' array"]
    elif isinstance(raw, list):
        records = raw
    else:
        return [f"dataset must be a list or object, got {type(raw).__name__}"]

    errors: list[str] = []
    seen_ids: set[str] = set()
    for item in records:
        if not isinstance(item, dict):
            errors.append(f"record is not an object: {item!r}")
            continue
        errors.extend(validate_record(item))
        rid = item.get("id")
        if rid:
            if rid in seen_ids:
                errors.append(f"duplicate scheme id: {rid!r}")
            seen_ids.add(rid)
    return errors

# ---------------------------------------------------------------------------
# Evidence chunking — produces retrieval units per scheme
# ---------------------------------------------------------------------------

def _operator_label(op: str, value: Any) -> str:
    if op == "in":
        return f"One of: {value}"
    if op == "gte":
        return f">= {value}"
    if op == "lte":
        return f"<= {value}"
    return str(value)


def build_chunks(scheme: SchemeRecord) -> list[dict[str, Any]]:
    """
    Split one scheme into retrieval-friendly evidence chunks.

    Each chunk is a dict with: scheme_id, scheme_name, source_url, chunk_type,
    text, checked_at, and (for evidence items) evidence_id, evidence_field,
    evidence_quote.
    """
    base = {
        "scheme_id": scheme.id,
        "scheme_name": scheme.name,
        "source_url": scheme.source_url or "",
        "checked_at": scheme.last_checked or "",
    }

    chunks: list[dict[str, Any]] = []

    # summary chunk
    tags = ", ".join(scheme.tags) if scheme.tags else ""
    text = f"{scheme.name}. {scheme.description}"
    if tags:
        text += f" Tags: {tags}."
    chunks.append({**base, "chunk_type": "summary", "text": text})

    # criteria chunk
    if scheme.criterion_list:
        lines = []
        for criterion in scheme.criterion_list:
            label = _operator_label(criterion.operator, criterion.value)
            lines.append(f"{criterion.field}: {label}")
        if scheme.criteria.notes:
            lines.append(f"Notes: {scheme.criteria.notes}")
        chunks.append({
            **base,
            "chunk_type": "criteria",
            "text": f"Eligibility criteria for {scheme.name}: " + "; ".join(lines) + ".",
        })

    # documents chunk
    if scheme.documents:
        chunks.append({
            **base,
            "chunk_type": "documents",
            "text": f"Required documents for {scheme.name}: " + ", ".join(scheme.documents) + ".",
        })

    # application steps chunk
    if scheme.application_steps:
        numbered = [
            f"{i}. {step}" for i, step in enumerate(scheme.application_steps, 1)
        ]
        chunks.append({
            **base,
            "chunk_type": "steps",
            "text": f"Application steps for {scheme.name}: " + " ".join(numbered),
        })

    # deadline chunk
    if scheme.deadline:
        dl = f"Deadline for {scheme.name}: {scheme.deadline}."
        if scheme.last_checked:
            dl += f" Last verified: {scheme.last_checked}."
        chunks.append({**base, "chunk_type": "deadline", "text": dl})

    # individual evidence items (verbatim quotes)
    for item in scheme.evidence:
        chunks.append({
            **base,
            "chunk_type": "evidence",
            "text": f"[{item.field}] {item.quote}",
            "evidence_id": item.id,
            "evidence_field": item.field,
            "evidence_quote": item.quote,
            "checked_at": item.checked_at or base["checked_at"],
        })

    return chunks
