"""
agent.py — EduSaarthi AI Gemini function-calling agent.

Architecture:
  - GeminiProvider: thin wrapper around the google-genai SDK.
    Isolated so a different provider can replace it later.
  - TOOL_REGISTRY: maps tool names → callables (bound to the repository).
  - TOOL_DECLARATIONS: SDK FunctionDeclaration objects (schema only, no logic).
  - AgentLoop: orchestrates the function-calling loop, conversation state,
    safety rails, and builds the final structured response.

Safety rails enforced here:
  - Max iterations (MAX_ITERATIONS from config).
  - Unregistered tool names → safe error result returned to model.
  - Malformed tool arguments → safe error result, loop continues.
  - Quota / timeout errors → specific HTTP-mappable exceptions.
  - Final answer text capped at MAX_ANSWER_LENGTH.
  - Conversation history lives in-process (resets on restart).
  - System prompt is static; tool results MUST NOT modify it.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError

from backend.config import Config
from backend.repository import BaseRepository
from backend import tools as tool_fns

# ---------------------------------------------------------------------------
# Conversation state (in-process, per-worker)
# ---------------------------------------------------------------------------

# Maps conversation_id → list[types.Content]
_CONVERSATIONS: dict[str, list[types.Content]] = {}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are EduSaarthi AI, a helpful and honest student opportunity navigator.
You help Indian students discover government scholarships, fellowships, and educational schemes.

Your core principles:
1. Ground every answer in tool results. Never invent scheme names, criteria, deadlines, or documents.
2. When tool results show unsatisfied or unknown criteria, report them honestly.
3. Cite only sources that appear in tool results (source_url fields).
4. If the student's question can be answered without tools, answer directly.
5. If information is missing from the knowledge base, say so clearly.
6. Never claim an application has been submitted on the student's behalf.
7. Always include the disclaimer when reporting eligibility.

Output style: concise, warm, and action-oriented. Use bullet points for lists.
"""


# ---------------------------------------------------------------------------
# Tool declarations (schema only — logic lives in tools.py)
# ---------------------------------------------------------------------------

_TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="search_schemes",
        description=(
            "Search the knowledge base for scholarship and scheme opportunities. "
            "Use this when the student asks about available schemes, scholarships, "
            "or opportunities. Returns a list with id, name, snippet, and source URL."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(
                    type=types.Type.STRING,
                    description="Search keywords, e.g. 'SC scholarship class 10 Maharashtra'",
                ),
                "education_level": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Optional. Filter by education level. "
                        "Valid values: 5th, 6th, 7th, 8th, 9th, 10th, 11th, 12th, "
                        "UG, PG, diploma, phd, any."
                    ),
                ),
                "state": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "Optional. Filter by Indian state name, e.g. 'Maharashtra'. "
                        "Omit for all-India results."
                    ),
                ),
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="check_eligibility",
        description=(
            "Check whether a student is eligible for a specific scheme. "
            "Performs deterministic comparisons against the scheme's criteria. "
            "Returns satisfied, unsatisfied, and unknown criteria separately."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "scheme_id": types.Schema(
                    type=types.Type.STRING,
                    description="The unique scheme ID from search_schemes results.",
                ),
                "student_info": types.Schema(
                    type=types.Type.OBJECT,
                    description=(
                        "Student profile. All fields are optional but more fields "
                        "give a more accurate result. "
                        "Keys: education_level (str), state (str), caste_category (str), "
                        "percentage (number 0-100), annual_family_income (number in INR), "
                        "gender (str), disability (bool)."
                    ),
                ),
            },
            required=["scheme_id", "student_info"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_requirements",
        description=(
            "Get the full requirements for a scheme: required documents, "
            "application steps, official URLs, and verification metadata. "
            "Use this before telling a student what documents to prepare."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "scheme_id": types.Schema(
                    type=types.Type.STRING,
                    description="The unique scheme ID.",
                ),
            },
            required=["scheme_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="verify_deadline",
        description=(
            "Check the recorded application deadline for a scheme. "
            "Returns the deadline, its status (current/past/stale/unverified/unknown), "
            "and a warning. Always call this before telling a student a deadline."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "scheme_id": types.Schema(
                    type=types.Type.STRING,
                    description="The unique scheme ID.",
                ),
            },
            required=["scheme_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="create_action_plan",
        description=(
            "Create a structured, step-by-step action plan for the student. "
            "Use this after checking eligibility and requirements to give the "
            "student clear next steps."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "goal": types.Schema(
                    type=types.Type.STRING,
                    description="The student's overall goal, e.g. 'Apply for SC scholarship'.",
                ),
                "scheme_ids": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING),
                    description="List of scheme IDs included in the plan.",
                ),
                "eligibility_results": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.OBJECT),
                    description="List of check_eligibility result objects.",
                ),
                "missing_info": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING),
                    description="List of information items the student still needs to gather.",
                ),
            },
            required=["goal", "scheme_ids", "eligibility_results", "missing_info"],
        ),
    ),
]

_GEMINI_TOOL = types.Tool(function_declarations=_TOOL_DECLARATIONS)


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class ProviderError(RuntimeError):
    """Raised by the provider for quota, timeout, or API errors."""
    def __init__(self, message: str, http_status: int = 503):
        super().__init__(message)
        self.http_status = http_status


class BaseProvider:
    """Interface: given a list of Contents, return a GenerateContentResponse."""

    def generate(
        self,
        contents: list[types.Content],
        model: str,
        tools: list[types.Tool],
        system_instruction: str,
    ) -> types.GenerateContentResponse:
        raise NotImplementedError


class GeminiProvider(BaseProvider):
    """Production provider — wraps google-genai SDK."""

    def __init__(self, api_key: str) -> None:
        import google.genai as genai
        self._client = genai.Client(api_key=api_key)

    def generate(
        self,
        contents: list[types.Content],
        model: str,
        tools: list[types.Tool],
        system_instruction: str,
    ) -> types.GenerateContentResponse:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tools,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="AUTO",
                )
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True,
            ),
            temperature=0.2,
        )
        try:
            return self._client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except ClientError as exc:
            code = exc.code if hasattr(exc, "code") else 400
            if code == 429:
                raise ProviderError(
                    "API quota exceeded. Please try again later.", http_status=429
                ) from exc
            raise ProviderError(
                f"API client error ({code}): {exc}", http_status=400
            ) from exc
        except ServerError as exc:
            raise ProviderError(
                "The AI model is temporarily unavailable. Please try again shortly.",
                http_status=503,
            ) from exc
        except APIError as exc:
            raise ProviderError(
                f"AI API error: {exc}", http_status=502
            ) from exc
        except Exception as exc:
            # Don't expose internals
            raise ProviderError(
                "An unexpected error occurred while contacting the AI model.",
                http_status=503,
            ) from exc


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

def build_tool_registry(repository: BaseRepository, config: Config) -> dict[str, Any]:
    """
    Return a dict mapping tool name → callable.
    Callables accept **kwargs matching the FunctionDeclaration parameters.
    Repository is injected here; tools never import it directly.
    """
    stale_days = config.deadline_stale_days
    max_results = config.max_search_results

    return {
        "search_schemes": lambda **kw: tool_fns.search_schemes(
            repository,
            query=kw["query"],
            education_level=kw.get("education_level"),
            state=kw.get("state"),
            max_results=max_results,
        ),
        "check_eligibility": lambda **kw: tool_fns.check_eligibility(
            repository,
            scheme_id=kw["scheme_id"],
            student_info=kw.get("student_info", {}),
        ),
        "get_requirements": lambda **kw: tool_fns.get_requirements(
            repository,
            scheme_id=kw["scheme_id"],
        ),
        "verify_deadline": lambda **kw: tool_fns.verify_deadline(
            repository,
            scheme_id=kw["scheme_id"],
            stale_days=stale_days,
        ),
        "create_action_plan": lambda **kw: tool_fns.create_action_plan(
            goal=kw["goal"],
            scheme_ids=kw.get("scheme_ids", []),
            eligibility_results=kw.get("eligibility_results", []),
            missing_info=kw.get("missing_info", []),
        ),
    }


# ---------------------------------------------------------------------------
# Agent response dataclass
# ---------------------------------------------------------------------------

@dataclass
class AgentResponse:
    conversation_id: str
    status: str          # "completed" | "needs_clarification" | "error"
    answer: str
    sources: list[dict[str, str]] = field(default_factory=list)
    events: list[dict[str, str]] = field(default_factory=list)
    action_plan: list[dict[str, Any]] = field(default_factory=list)
    # Optional structured fields — only populated when tool results support them.
    clarification: Optional[dict[str, Any]] = None
    matches: list[dict[str, Any]] = field(default_factory=list)
    eligibility: Optional[dict[str, list[str]]] = None
    documents: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

class AgentLoop:
    """
    Manages the Gemini function-calling loop for a single request.

    Thread-safety note: _CONVERSATIONS is a module-level dict, which is
    GIL-protected for simple operations in CPython. For multi-worker
    deployments, replace with Redis or a DB-backed session store.
    """

    def __init__(
        self,
        provider: BaseProvider,
        tool_registry: dict[str, Any],
        config: Config,
    ) -> None:
        self._provider = provider
        self._registry = tool_registry
        self._config = config

    def run(
        self,
        message: str,
        conversation_id: Optional[str] = None,
    ) -> AgentResponse:
        """
        Process one user message, execute tool calls, and return a structured response.

        Raises ProviderError for quota/timeout errors (caller maps to HTTP status).
        """
        # Resolve or create conversation
        if not conversation_id or conversation_id not in _CONVERSATIONS:
            conversation_id = str(uuid.uuid4())
            _CONVERSATIONS[conversation_id] = []

        history: list[types.Content] = _CONVERSATIONS[conversation_id]

        # Append user message
        history.append(types.Content(role="user", parts=[types.Part(text=message)]))

        events: list[dict[str, str]] = []
        action_plan: list[dict[str, Any]] = []
        sources_map: dict[str, dict[str, str]] = {}  # id → source record
        matches: list[dict[str, Any]] = []
        eligibility: dict[str, list[str]] = {}
        documents: list[str] = []
        steps: list[str] = []

        # ------------------------------------------------------------------
        # Function-calling loop
        # ------------------------------------------------------------------
        final_text = ""
        iterations = 0
        max_iter = self._config.max_iterations

        while iterations < max_iter:
            iterations += 1

            response = self._provider.generate(
                contents=history,
                model=self._config.gemini_model,
                tools=[_GEMINI_TOOL],
                system_instruction=SYSTEM_PROMPT,
            )

            candidate = response.candidates[0] if response.candidates else None
            if candidate is None:
                final_text = "I'm sorry, I couldn't generate a response. Please try again."
                break

            # Append model turn to history
            history.append(candidate.content)

            finish_reason = candidate.finish_reason

            # Collect any function calls in this response
            function_calls = [
                p.function_call
                for p in (candidate.content.parts or [])
                if p.function_call is not None
            ]

            if not function_calls:
                # No tool calls → extract final text
                text_parts = [
                    p.text for p in (candidate.content.parts or [])
                    if p.text
                ]
                final_text = "\n".join(text_parts).strip()

                # Handle non-STOP finish reasons
                if finish_reason == types.FinishReason.MAX_TOKENS:
                    final_text = (
                        (final_text + " [Note: response was truncated due to length limit.]")
                        if final_text
                        else "Response was truncated. Please ask a more specific question."
                    )
                elif finish_reason == types.FinishReason.MALFORMED_FUNCTION_CALL:
                    final_text = (
                        "I encountered an issue processing your request. "
                        "Please rephrase your question."
                    )
                elif finish_reason in (
                    types.FinishReason.SAFETY,
                    types.FinishReason.PROHIBITED_CONTENT,
                ):
                    final_text = (
                        "I'm unable to respond to that request due to content policy."
                    )
                break

            # ------------------------------------------------------------------
            # Execute tool calls (sequential and parallel supported)
            # ------------------------------------------------------------------
            tool_result_parts: list[types.Part] = []

            for fc in function_calls:
                tool_name = fc.name or ""
                raw_args = fc.args or {}

                if tool_name not in self._registry:
                    # Unregistered tool — return structured error to model
                    result = {
                        "error": True,
                        "error_code": "UNREGISTERED_TOOL",
                        "message": (
                            f"Tool '{tool_name}' is not registered. "
                            f"Available tools: {list(self._registry.keys())}"
                        ),
                    }
                    events.append({
                        "tool": tool_name,
                        "status": "error",
                        "summary": f"Unregistered tool: {tool_name}",
                    })
                else:
                    try:
                        # Validate args are dict-like
                        if not isinstance(raw_args, dict):
                            raise ValueError(
                                f"Tool arguments must be an object, got {type(raw_args).__name__}"
                            )
                        result = self._registry[tool_name](**raw_args)
                        is_error = isinstance(result, dict) and result.get("error") is True
                        events.append({
                            "tool": tool_name,
                            "status": "error" if is_error else "ok",
                            "summary": _summarize_result(tool_name, result),
                        })
                        # Collect sources, eligibility, requirements, matches
                        _collect_optional_fields(
                            tool_name, result, sources_map, matches,
                            eligibility, documents, steps,
                        )
                        # Collect action plan steps
                        if tool_name == "create_action_plan" and isinstance(result, dict):
                            action_plan = result.get("steps", [])
                    except Exception as exc:
                        result = {
                            "error": True,
                            "error_code": "TOOL_EXECUTION_ERROR",
                            "message": f"Tool '{tool_name}' failed: {exc}",
                        }
                        events.append({
                            "tool": tool_name,
                            "status": "error",
                            "summary": f"Execution error: {exc}",
                        })

                tool_result_parts.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response={"output": result},
                    )
                )

            # Append tool results as "tool" role turn
            history.append(
                types.Content(role="tool", parts=tool_result_parts)
            )

        else:
            # Iteration limit hit
            final_text = (
                "I've reached the maximum number of reasoning steps for this request. "
                "Please try a more specific question or break your request into smaller parts."
            )
            events.append({
                "tool": "_agent",
                "status": "error",
                "summary": f"Iteration limit ({max_iter}) reached",
            })

        # Persist updated history
        _CONVERSATIONS[conversation_id] = history

        # Cap answer length
        max_len = self._config.max_answer_length
        if len(final_text) > max_len:
            final_text = final_text[:max_len] + "…"

        # Determine status
        status = _infer_status(final_text, events)

        # Structured clarification when the agent needs more information.
        clarification = None
        if status == "needs_clarification":
            clarification = {"question": final_text, "options": []}

        return AgentResponse(
            conversation_id=conversation_id,
            status=status,
            answer=final_text,
            sources=list(sources_map.values()),
            events=events,
            action_plan=action_plan,
            clarification=clarification,
            matches=matches,
            eligibility=eligibility or None,
            documents=documents,
            steps=steps,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _summarize_result(tool_name: str, result: dict[str, Any]) -> str:
    """Build a brief human-readable summary of a tool result for the events list."""
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result.get('message', 'unknown')}"
    if tool_name == "search_schemes":
        count = result.get("result_count", 0)
        return f"Found {count} scheme(s)"
    if tool_name == "check_eligibility":
        return f"Status: {result.get('status', 'unknown')}"
    if tool_name == "get_requirements":
        docs = len(result.get("documents") or [])
        return f"{docs} document(s) required"
    if tool_name == "verify_deadline":
        return f"Deadline status: {result.get('deadline_status', 'unknown')}"
    if tool_name == "create_action_plan":
        steps = len(result.get("steps") or [])
        return f"Plan with {steps} step(s) created"
    return "Completed"


def _extract_sources(result: dict[str, Any], sources_map: dict[str, dict[str, str]]) -> None:
    """Extract source metadata from a tool result and merge into the sources map."""
    if not isinstance(result, dict):
        return

    # search_schemes → list of results
    for item in result.get("results") or []:
        if isinstance(item, dict) and item.get("id") and item.get("source_url"):
            sid = item["id"]
            sources_map[sid] = {
                "id": sid,
                "title": item.get("name", sid),
                "url": item["source_url"],
            }

    # check_eligibility / get_requirements / verify_deadline → single scheme
    sid = result.get("scheme_id")
    url = result.get("source_url")
    name = result.get("scheme_name", sid)
    if sid and url:
        sources_map[sid] = {"id": sid, "title": name or sid, "url": url}


def _collect_optional_fields(
    tool_name: str,
    result: dict[str, Any],
    sources_map: dict[str, dict[str, str]],
    matches: list[dict[str, Any]],
    eligibility: dict[str, list[str]],
    documents: list[str],
    steps: list[str],
) -> None:
    """Extract client-facing matches/eligibility/documents/steps from tool results."""
    if not isinstance(result, dict) or result.get("error") is True:
        return
    _extract_sources(result, sources_map)

    if tool_name == "search_schemes":
        _collect_matches(result, matches)
    elif tool_name == "check_eligibility":
        _collect_eligibility(result, eligibility)
    elif tool_name == "get_requirements":
        _collect_requirements(result, documents, steps)


def _collect_matches(result: dict[str, Any], matches: list[dict[str, Any]]) -> None:
    """Collect scheme candidates surfaced by search_schemes (no fabricated fields)."""
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("name") or "").strip() or str(item.get("id") or "").strip()
        if not title:
            continue
        matches.append({
            "id": str(item.get("id") or "").strip(),
            "title": title,
            "summary": str(item.get("description_snippet") or "").strip(),
            "url": str(item.get("source_url") or "").strip(),
        })


def _eligibility_line(item: dict[str, Any], met: bool) -> str:
    """Human-readable line for one eligibility criterion result."""
    name = str(item.get("criterion") or "").strip() or "criterion"
    if met:
        required = str(item.get("required") or "").strip()
        return f"{name} (required: {required})" if required else name
    note = str(item.get("note") or "").strip()
    return f"{name}: {note}" if note else name


def _collect_eligibility(result: dict[str, Any], holder: dict[str, list[str]]) -> None:
    """Collect eligibility rows: met / missing (not met) / unknown."""
    holder["met"] = [
        _eligibility_line(c, met=True)
        for c in (result.get("satisfied_criteria") or [])
        if isinstance(c, dict)
    ]
    holder["missing"] = [
        _eligibility_line(c, met=False)
        for c in (result.get("unsatisfied_criteria") or [])
        if isinstance(c, dict)
    ]
    holder["unknown"] = [
        _eligibility_line(c, met=False)
        for c in (result.get("unknown_criteria") or [])
        if isinstance(c, dict)
    ]


def _collect_requirements(
    result: dict[str, Any],
    documents: list[str],
    steps: list[str],
) -> None:
    """Collect required documents and application steps from get_requirements."""
    for doc in result.get("documents") or []:
        if isinstance(doc, str) and doc.strip():
            documents.append(doc)
    for step in result.get("application_steps") or []:
        if isinstance(step, str) and step.strip():
            steps.append(step)


def _infer_status(answer: str, events: list[dict[str, str]]) -> str:
    """
    Infer the response status from the answer text and tool events.
    Returns "needs_clarification" if the answer is a question,
    "completed" otherwise.
    """
    if answer.strip().endswith("?"):
        return "needs_clarification"
    return "completed"
