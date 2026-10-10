"""
agent.py — EduSaarthi AI function-calling agent.

Architecture:
  - OpenRouterProvider: production provider speaking the OpenAI-compatible
    Chat Completions API exposed by OpenRouter.
  - GeminiProvider: alternative provider wrapping the google-genai SDK.
    Both implement BaseProvider, so either can be wired in app.py.
  - google-genai types are the loop's internal representation for contents,
    tools and responses; providers translate at the wire boundary.
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
import urllib.error
import urllib.request
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
8. When you need specific information from the student before you can
   continue, call ask_clarification with the question and short options.

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
    types.FunctionDeclaration(
        name="ask_clarification",
        description=(
            "Ask the student a clarifying question when you need specific "
            "information before you can continue (e.g. state, education level, "
            "category). Prefer this over ending your answer with a question. "
            "Provide short options when the choices are enumerable."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "question": types.Schema(
                    type=types.Type.STRING,
                    description="The clarifying question to ask the student.",
                ),
                "options": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING),
                    description="Optional short answer options for the student.",
                ),
            },
            required=["question"],
        ),
    ),
]

_GEMINI_TOOL = types.Tool(function_declarations=_TOOL_DECLARATIONS)

# Agent-internal tool: intercepted by AgentLoop, never executed as a data tool.
CLARIFICATION_TOOL_NAME = "ask_clarification"


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
        self._client = genai.Client(api_key=api_key, http_options={'timeout': 120_000})

    def generate(
        self,
        contents: list[types.Content],
        model: str,
        tools: list[types.Tool],
        system_instruction: str,
    ) -> types.GenerateContentResponse:
        import time
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
            # Add timeout? Not explicitly supported in config without http_options, wait...
        )
        try:
            start_time = time.perf_counter()
            # Set http_options for timeout
            res = self._client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            end_time = time.perf_counter()
            print(f"[TIMING] Gemini API generate_content duration: {end_time - start_time:.3f}s")
            return res
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


class OpenRouterProvider(BaseProvider):
    """
    Production provider — speaks the OpenAI-compatible Chat Completions API
    exposed by OpenRouter ({base_url}/chat/completions).

    Translates the loop's google-genai typed contents/tools to wire JSON and
    the response back, so AgentLoop stays provider-agnostic.
    """

    _SCHEMA_TYPES = {
        "OBJECT": "object",
        "STRING": "string",
        "ARRAY": "array",
        "INTEGER": "integer",
        "NUMBER": "number",
        "BOOLEAN": "boolean",
    }

    _FINISH_REASONS = {
        "stop": types.FinishReason.STOP,
        "tool_calls": types.FinishReason.STOP,
        "function_call": types.FinishReason.STOP,
        "length": types.FinishReason.MAX_TOKENS,
        "content_filter": types.FinishReason.PROHIBITED_CONTENT,
    }

    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1") -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def generate(
        self,
        contents: list[types.Content],
        model: str,
        tools: list[types.Tool],
        system_instruction: str,
    ) -> types.GenerateContentResponse:
        import time

        messages = [{"role": "system", "content": system_instruction}]
        messages.extend(self._contents_to_messages(contents))
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }
        wire_tools = self._tools_to_openai(tools)
        if wire_tools:
            payload["tools"] = wire_tools

        try:
            start_time = time.perf_counter()
            data = self._post(payload)
            end_time = time.perf_counter()
            print(f"[TIMING] OpenRouter generate duration: {end_time - start_time:.3f}s")
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                "An unexpected error occurred while contacting the AI model.",
                http_status=503,
            ) from exc

        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(
                "The AI model returned no response. Please try again.",
                http_status=503,
            )
        choice = choices[0]
        message = choice.get("message") or {}

        parts: list[types.Part] = []
        text = message.get("content")
        if text:
            parts.append(types.Part(text=text))
        for tool_call in message.get("tool_calls") or []:
            fn = tool_call.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except Exception:
                args = {}
            if not isinstance(args, dict):
                args = {}
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(name=fn.get("name") or "", args=args)
                )
            )
        if not parts:
            parts = [types.Part(text="")]

        finish_reason = self._FINISH_REASONS.get(
            str(choice.get("finish_reason") or "stop").lower(),
            types.FinishReason.STOP,
        )
        candidate = types.Candidate(
            content=types.Content(role="model", parts=parts),
            finish_reason=finish_reason,
        )
        return types.GenerateContentResponse(candidates=[candidate])

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "X-Title": "EduSaarthi AI",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                body = json.loads(exc.read().decode("utf-8"))
                detail = (body.get("error") or {}).get("message", "")
            except Exception:
                pass
            code = exc.code
            if code == 429:
                raise ProviderError(
                    "API quota exceeded. Please try again later.", http_status=429
                ) from exc
            if code == 401:
                raise ProviderError(
                    "AI service authentication failed. Check OPENROUTER_API_KEY.",
                    http_status=502,
                ) from exc
            if code >= 500:
                raise ProviderError(
                    "The AI model is temporarily unavailable. Please try again shortly.",
                    http_status=503,
                ) from exc
            raise ProviderError(
                f"API client error ({code}): {detail}", http_status=400
            ) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            raise ProviderError(
                "The AI model is temporarily unavailable. Please try again shortly.",
                http_status=503,
            ) from exc

    @classmethod
    def _tools_to_openai(cls, tools: list[types.Tool]) -> list[dict[str, Any]]:
        declarations: list[dict[str, Any]] = []
        for tool in tools:
            for fn in (getattr(tool, "function_declarations", None) or []):
                entry: dict[str, Any] = {
                    "name": fn.name or "",
                    "description": fn.description or "",
                }
                parameters = cls._schema_to_json(fn.parameters)
                if parameters:
                    entry["parameters"] = parameters
                declarations.append({"type": "function", "function": entry})
        return declarations

    @classmethod
    def _schema_to_json(cls, schema: Optional[types.Schema]) -> Optional[dict[str, Any]]:
        if schema is None:
            return None
        out: dict[str, Any] = {}
        raw_type = getattr(schema.type, "name", schema.type)
        key = str(raw_type).upper().split(".")[-1]
        out["type"] = cls._SCHEMA_TYPES.get(key, key.lower())
        if schema.description:
            out["description"] = schema.description
        if schema.properties:
            out["properties"] = {
                name: cls._schema_to_json(prop) for name, prop in schema.properties.items()
            }
        if schema.items:
            out["items"] = cls._schema_to_json(schema.items)
        if schema.required:
            out["required"] = list(schema.required)
        return out

    @staticmethod
    def _contents_to_messages(contents: list[types.Content]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        pending_call_ids: list[str] = []

        for content in contents:
            if content.role == "model":
                text_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                for part in (content.parts or []):
                    if part.text:
                        text_parts.append(part.text)
                    if part.function_call is not None:
                        call_id = f"call_{len(messages)}_{len(tool_calls)}"
                        tool_calls.append({
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": part.function_call.name or "",
                                "arguments": json.dumps(part.function_call.args or {}),
                            },
                        })
                assistant: dict[str, Any] = {
                    "role": "assistant",
                    "content": "\n".join(text_parts) or None,
                }
                if tool_calls:
                    assistant["tool_calls"] = tool_calls
                    pending_call_ids = [call["id"] for call in tool_calls]
                messages.append(assistant)
                continue

            text_parts = []
            for part in (content.parts or []):
                if part.function_response is not None:
                    payload = part.function_response.response
                    call_id = (
                        pending_call_ids.pop(0)
                        if pending_call_ids
                        else f"call_{len(messages)}_0"
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(payload if payload is not None else {}, default=str),
                    })
                elif part.text:
                    text_parts.append(part.text)
            if text_parts:
                messages.append({"role": "user", "content": "\n".join(text_parts)})

        return messages


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
        student_profile: Optional[dict[str, Any]] = None,
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
        tool_cache = {}
        clarification_request: Optional[dict[str, Any]] = None

        while iterations < max_iter:
            iterations += 1

            response = self._provider.generate(
                contents=history,
                model=self._config.openrouter_model,
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

                if tool_name == CLARIFICATION_TOOL_NAME:
                    question = str(raw_args.get("question") or "").strip()
                    options = [
                        str(opt).strip()
                        for opt in (raw_args.get("options") or [])
                        if str(opt).strip()
                    ][:6]
                    if question:
                        clarification_request = {
                            "question": question,
                            "options": options,
                        }
                        events.append({
                            "tool": tool_name,
                            "status": "completed",
                            "summary": "Asked the student a clarifying question",
                        })
                    else:
                        events.append({
                            "tool": tool_name,
                            "status": "error",
                            "summary": "Clarification request missing a question",
                        })
                    tool_result_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"output": {"status": "clarification_requested"}},
                        )
                    )
                    continue

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
                        import json, time
                        
                        if tool_name == "check_eligibility" and student_profile:
                            raw_args["student_info"] = {**student_profile, **raw_args.get("student_info", {})}
                        
                        # Generate cache key
                        cache_key = f"{tool_name}:{json.dumps(raw_args, sort_keys=True)}"
                        
                        if cache_key in tool_cache:
                            result = tool_cache[cache_key]
                            print(f"[CACHE] Hit for {tool_name}")
                        else:
                            start_tool = time.perf_counter()
                            result = self._registry[tool_name](**raw_args)
                            end_tool = time.perf_counter()
                            print(f"[TIMING] Tool {tool_name} duration: {end_tool - start_tool:.3f}s")
                            tool_cache[cache_key] = result

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

            # Append tool results as "user" role turn (Gemini API requirement)
            history.append(
                types.Content(role="user", parts=tool_result_parts)
            )

            if clarification_request:
                break

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

        # Determine status: an explicit ask_clarification call is authoritative.
        # Otherwise a question from the agent counts as clarification only when
        # the answer is not grounded in tool results (e.g. no trailing offers
        # like "Would you like me to check eligibility?").
        clarification = clarification_request
        if clarification is not None:
            status = "needs_clarification"
            if clarification["question"]:
                final_text = clarification["question"]
        else:
            grounded = bool(
                sources_map or matches or eligibility or documents or steps
                or action_plan
            )
            status = _infer_status(final_text, grounded=grounded)
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
    seen = {
        str(item.get("id") or item.get("title") or "").strip()
        for item in matches
        if isinstance(item, dict)
    }
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("name") or "").strip() or str(item.get("id") or "").strip()
        if not title:
            continue
        mid = str(item.get("id") or "").strip()
        key = mid or title
        if key in seen:
            continue
        seen.add(key)
        matches.append({
            "id": mid,
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


def _infer_status(answer: str, grounded: bool = False) -> str:
    """
    Return the response status.

    "needs_clarification" when the agent is asking the student a question and
    the answer carries no grounded tool results; "completed" otherwise.
    """
    if grounded:
        return "completed"
    if answer.strip().endswith("?"):
        return "needs_clarification"
    return "completed"
