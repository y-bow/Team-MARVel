"""
repository.py — EduSaarthi AI data access layer.

Provides a read-only abstraction over the scheme knowledge base.
The first implementation reads from a JSON file at startup.

Design rules:
  - Tools MUST only call repository methods; they never touch file paths
    or parse JSON themselves.
  - All public methods return Python objects (SchemeRecord or dicts),
    never raw JSON strings.
  - A future PostgreSQL or vector-search implementation can replace
    JSONRepository by implementing the same BaseRepository interface.
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Optional

from backend.schemas import SchemeRecord, scheme_from_dict


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class BaseRepository(ABC):
    """Interface that all repository implementations must satisfy."""

    @abstractmethod
    def search(
        self,
        query: str,
        education_level: Optional[str] = None,
        state: Optional[str] = None,
        max_results: int = 10,
    ) -> list[SchemeRecord]:
        """
        Keyword search with optional structured filters.

        Returns up to *max_results* SchemeRecords ordered by relevance.
        Returns [] when nothing matches — never raises on "no results".
        """

    @abstractmethod
    def get_by_id(self, scheme_id: str) -> Optional[SchemeRecord]:
        """
        Return the SchemeRecord for *scheme_id*, or None if not found.
        Never raises on unknown IDs.
        """

    @abstractmethod
    def get_requirements(self, scheme_id: str) -> Optional[dict[str, Any]]:
        """
        Return a dict with documents, application_steps, source_url,
        verified, and last_checked for *scheme_id*.
        Returns None if the scheme does not exist.
        Distinct from "empty requirements list" — callers must check for None.
        """

    @abstractmethod
    def count(self) -> int:
        """Return total number of schemes in the repository."""

    def data_quality(self, stale_days: int = 30) -> dict[str, Any]:
        """
        Return a summary of record freshness for operational visibility.

        Counts are derived deterministically from stored fields — never from
        model output. 'stale' means last_checked is missing or older than
        stale_days; 'past_deadlines' counts dates earlier than today.
        """
        today = date.today()
        verified = 0
        unverified = 0
        past = 0
        unknown_deadline = 0
        never_checked = 0
        stale = 0
        oldest: Optional[str] = None

        for scheme in self._records_for_quality():
            if scheme.verified:
                verified += 1
            else:
                unverified += 1

            if not scheme.deadline:
                unknown_deadline += 1
            else:
                try:
                    if date.fromisoformat(scheme.deadline) < today:
                        past += 1
                except ValueError:
                    unknown_deadline += 1

            checked = scheme.last_checked
            if not checked:
                never_checked += 1
                stale += 1
            else:
                if oldest is None or checked < oldest:
                    oldest = checked
                try:
                    if (today - date.fromisoformat(checked)).days > stale_days:
                        stale += 1
                except ValueError:
                    stale += 1

        return {
            "as_of": today.isoformat(),
            "records": self.count(),
            "verified": verified,
            "unverified": unverified,
            "past_deadlines": past,
            "unknown_deadlines": unknown_deadline,
            "never_checked": never_checked,
            "stale_records": stale,
            "oldest_last_checked": oldest,
        }

    def _records_for_quality(self) -> list["SchemeRecord"]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# JSON implementation
# ---------------------------------------------------------------------------

class JSONRepository(BaseRepository):
    """
    Read-only repository backed by a JSON file.

    The file is loaded once at construction time and cached in memory.
    Suitable for development and single-process deployments.

    Expected JSON format (see schemas.py for full field reference):
      [
        {
          "id": "unique-slug",
          "name": "Scheme Name",
          "description": "...",
          "criteria": { ... },
          ...
        },
        ...
      ]
    """

    def __init__(self, data_path: str) -> None:
        self._data_path = data_path
        self._schemes: dict[str, SchemeRecord] = {}
        self._ordered: list[SchemeRecord] = []
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load and parse the JSON file. Raises on missing file or invalid JSON."""
        if not os.path.isfile(self._data_path):
            raise FileNotFoundError(
                f"Knowledge-base file not found: {self._data_path!r}. "
                "Set DATA_PATH env var or place schemes.json at data/schemes.json."
            )

        with open(self._data_path, encoding="utf-8") as fh:
            raw: Any = json.load(fh)

        if isinstance(raw, dict):
            raw = raw.get("schemes")

        if not isinstance(raw, list):
            raise ValueError(
                f"Knowledge-base file must be a JSON array (v1) or an object "
                f"with a 'schemes' array (v2), got {type(raw).__name__}: "
                f"{self._data_path!r}"
            )

        skipped = 0
        for idx, item in enumerate(raw):
            try:
                record = scheme_from_dict(item)
                self._schemes[record.id] = record
                self._ordered.append(record)
            except (ValueError, TypeError) as exc:
                # Skip malformed records but don't crash the whole load
                skipped += 1
                print(f"[repository] Skipping record at index {idx}: {exc}")

        print(
            f"[repository] Loaded {len(self._schemes)} schemes "
            f"({skipped} skipped) from {self._data_path!r}"
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        education_level: Optional[str] = None,
        state: Optional[str] = None,
        max_results: int = 10,
    ) -> list[SchemeRecord]:
        """
        Keyword search across name, description, and tags.
        Applies optional structured filters on education_level and state.
        Returns up to max_results results, ordered by match score (descending).
        Returns [] on no match.
        """
        query_tokens = _tokenize(query)
        results: list[tuple[int, SchemeRecord]] = []

        for scheme in self._ordered:
            # Structured filters first (fast rejection)
            if education_level and not _matches_education(scheme, education_level):
                continue
            if state and not _matches_state(scheme, state):
                continue

            # Keyword relevance score
            score = _score(scheme, query_tokens)
            if score > 0:
                results.append((score, scheme))

        results.sort(key=lambda t: t[0], reverse=True)
        return [r for _, r in results[:max_results]]

    def get_by_id(self, scheme_id: str) -> Optional[SchemeRecord]:
        return self._schemes.get(scheme_id)

    def get_requirements(self, scheme_id: str) -> Optional[dict[str, Any]]:
        scheme = self._schemes.get(scheme_id)
        if scheme is None:
            return None
        return {
            "scheme_id": scheme.id,
            "scheme_name": scheme.name,
            "documents": scheme.documents,
            "application_steps": scheme.application_steps,
            "source_url": scheme.source_url,
            "verified": scheme.verified,
            "last_checked": scheme.last_checked,
            "information_complete": _requirements_complete(scheme),
        }

    def count(self) -> int:
        return len(self._schemes)

    def _records_for_quality(self) -> list[SchemeRecord]:
        return list(self._ordered)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _score(scheme: SchemeRecord, query_tokens: list[str]) -> int:
    """Simple TF-style score: count query token occurrences in searchable fields."""
    if not query_tokens:
        return 1  # Empty query matches everything

    haystack = " ".join([
        scheme.name,
        scheme.description,
        " ".join(scheme.tags),
        scheme.criteria.state or "",
        " ".join(scheme.criteria.education_levels or []),
    ]).lower()

    return sum(haystack.count(tok) for tok in query_tokens)


def _matches_education(scheme: SchemeRecord, level: str) -> bool:
    """Return True if the scheme accepts the requested education level."""
    levels = scheme.criteria.education_levels
    if not levels:
        return True  # No restriction
    normalized = [lv.lower().strip() for lv in levels]
    return "any" in normalized or level.lower().strip() in normalized


def _matches_state(scheme: SchemeRecord, state: str) -> bool:
    """Return True only if the scheme is restricted to the requested state.

    All-India schemes (no state restriction) do NOT match a specific-state
    filter; omit the state filter to see all-India results. The sentinel
    values "all india" / "all" / "any" match every scheme.
    """
    scheme_state = scheme.criteria.state
    state_norm = state.lower().strip()
    if state_norm in ("all india", "all", "any"):
        return True
    if not scheme_state:
        return False
    return scheme_state.lower().strip() == state_norm


def _requirements_complete(scheme: SchemeRecord) -> bool:
    """
    Returns True only if all key requirement fields are non-empty.
    'information_complete: false' signals to the UI that data may be partial.
    """
    return bool(
        scheme.documents
        and scheme.application_steps
        and scheme.source_url
        and scheme.last_checked
    )
