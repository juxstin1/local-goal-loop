from __future__ import annotations

import json
import os
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from graph_engineer.prompts import system_prompt, user_payload

PacketT = TypeVar("PacketT", bound=BaseModel)


class _WireFileReplacement(BaseModel):
    path: str
    content: str


class _WirePatchDraft(BaseModel):
    summary: str
    replacements: list[_WireFileReplacement]
    test_ids: list[str]
    rationale: str = Field(description="One short sentence explaining the edit.")


class _WireRequirementResult(BaseModel):
    requirement_id: str
    status: Literal["proved", "unproved", "contradicted"]
    evidence: list[str]
    explanation: str


class _WireReviewDraft(BaseModel):
    requirement_results: list[_WireRequirementResult]
    findings: list[str]
    next_action: str


WIRE_SCHEMAS: dict[str, type[BaseModel]] = {
    "patch": _WirePatchDraft,
    "review": _WireReviewDraft,
}


def wire_tool(role: str, schema: type[BaseModel], payload: dict[str, Any]) -> dict[str, Any]:
    parameters = schema.model_json_schema()
    properties = parameters["properties"]
    if role == "plan":
        properties["files"]["items"]["enum"] = payload["allowed_write_paths"]
        properties["test_ids"]["items"]["enum"] = payload["registered_test_ids"]
        parameters["$defs"]["PlanStep"]["properties"]["evidence_ids"]["items"]["enum"] = [
            item["id"] for item in payload["context"]["evidence"]
        ]
    elif role == "patch":
        parameters["$defs"]["_WireFileReplacement"]["properties"]["path"]["enum"] = payload[
            "approved_plan"
        ]["files"]
        properties["test_ids"]["items"]["enum"] = payload["approved_plan"]["test_ids"]
    elif role == "review":
        requirement = parameters["$defs"]["_WireRequirementResult"]["properties"]
        requirement["requirement_id"]["enum"] = [
            item["id"] for item in payload["goal"]["requirements"]
        ]
        requirement["evidence"]["items"]["enum"] = payload["available_evidence"]
    return {"type": "function", "function": {"name": schema.__name__, "parameters": parameters}}


def malformed_tool_response(error: Exception) -> bool:
    text = str(error)
    return (
        getattr(error, "status_code", None) == 500 or text.startswith("Error code: 500")
    ) and "Failed to parse tool call arguments as JSON" in text


class RoleModel(Protocol):
    def invoke(self, role: str, schema: type[PacketT], payload: dict[str, Any]) -> PacketT: ...


class LocalChatRoleModel:
    def __init__(
        self,
        chat_model: Any | None = None,
        *,
        packet_attempts: int | None = None,
        trace_path: Path | None = None,
    ) -> None:
        self._model = chat_model or ChatOpenAI(
            model=os.getenv("LOCAL_MODEL_NAME", "local"),
            base_url=os.getenv("LOCAL_MODEL_BASE_URL", "http://127.0.0.1:8080/v1"),
            api_key="local-no-secret",
            temperature=0,
            timeout=float(os.getenv("LOCAL_MODEL_TIMEOUT_SECONDS", "120")),
            max_tokens=int(os.getenv("LOCAL_MODEL_MAX_TOKENS", "2048")),
            max_retries=1,
            use_responses_api=False,
            stream_usage=False,
        )
        self._packet_attempts = (
            packet_attempts
            if packet_attempts is not None
            else int(os.getenv("LOCAL_MODEL_PACKET_ATTEMPTS", "3"))
        )
        if self._packet_attempts < 1:
            raise ValueError("packet_attempts must be at least one")
        self.trace_path = trace_path
        self.malformed_response_count = 0

    def _trace(self, record: dict[str, Any]) -> None:
        if self.trace_path is not None:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def invoke(self, role: str, schema: type[PacketT], payload: dict[str, Any]) -> PacketT:
        wire_schema = WIRE_SCHEMAS.get(role, schema)
        bound = self._model.bind_tools(
            [wire_tool(role, wire_schema, payload)],
            tool_choice="required",
            parallel_tool_calls=False,
        )
        messages = [
            SystemMessage(content=system_prompt(role)),
            HumanMessage(content=user_payload(payload)),
        ]
        last_error: ValueError | None = None
        for attempt in range(1, self._packet_attempts + 1):
            try:
                message = bound.invoke(messages)
            except Exception as error:
                self._trace(
                    {
                        "role": role,
                        "attempt": attempt,
                        "input": payload,
                        "error_type": type(error).__name__,
                        "error": str(error)[:2000],
                    }
                )
                if not malformed_tool_response(error):
                    raise
                self.malformed_response_count += 1
                if attempt == self._packet_attempts:
                    raise
                messages.append(
                    HumanMessage(
                        content=(
                            "Your last tool response was malformed or truncated JSON. "
                            "Return one complete tool call. Use one-sentence explanations. "
                            "Do not calculate file hashes; the host fills them."
                        )
                    )
                )
                continue
            self._trace(
                {
                    "role": role,
                    "attempt": attempt,
                    "input": payload,
                    "response": message.model_dump(mode="json"),
                }
            )
            try:
                if len(message.tool_calls) != 1:
                    raise ValueError(
                        f"role {role!r} must return exactly one structured call; "
                        f"received {len(message.tool_calls)}"
                    )
                call = message.tool_calls[0]
                if call["name"] != wire_schema.__name__:
                    raise ValueError(
                        f"role {role!r} returned tool {call['name']!r}, "
                        f"expected {wire_schema.__name__!r}"
                    )
                value = wire_schema.model_validate(call["args"]).model_dump(mode="json")
                if role == "patch":
                    evidence = {item["path"]: item for item in payload["context"]["evidence"]}
                    for replacement in value["replacements"]:
                        path = replacement["path"]
                        if path not in payload["approved_plan"]["files"] or path not in evidence:
                            raise ValueError(
                                f"replacement path is not an approved evidence file: {path}"
                            )
                        replacement["expected_sha256"] = evidence[path]["sha256"]
                return schema.model_validate(value)
            except ValueError as error:
                last_error = error
                if attempt == self._packet_attempts:
                    raise
                correction = (
                    "PACKET VALIDATION FAILED. Return exactly one corrected "
                    f"{wire_schema.__name__} tool call. Error: {error}"
                )
                messages.append(message)
                if message.tool_calls:
                    messages.extend(
                        ToolMessage(content=correction, tool_call_id=call["id"])
                        for call in message.tool_calls
                    )
                else:
                    messages.append(HumanMessage(content=correction))
        raise AssertionError(f"unreachable packet retry state: {last_error}")


class ScriptedRoleModel:
    """Deterministic role responses for graph and safety tests."""

    def __init__(self, responses: dict[str, list[dict[str, Any] | BaseModel]]) -> None:
        self._responses = defaultdict(deque)
        for role, values in responses.items():
            self._responses[role].extend(values)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def invoke(self, role: str, schema: type[PacketT], payload: dict[str, Any]) -> PacketT:
        self.calls.append((role, payload))
        if not self._responses[role]:
            raise AssertionError(f"no scripted response remains for role {role!r}")
        value = self._responses[role].popleft()
        return schema.model_validate(value)


class FunctionalRoleModel:
    def __init__(self, handlers: dict[str, Callable[[dict[str, Any]], Any]]) -> None:
        self.handlers = handlers
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def invoke(self, role: str, schema: type[PacketT], payload: dict[str, Any]) -> PacketT:
        self.calls.append((role, payload))
        return schema.model_validate(self.handlers[role](payload))
