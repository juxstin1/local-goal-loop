from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FrozenPacket(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Requirement(FrozenPacket):
    id: str = Field(pattern=r"^REQ-[0-9]{3}$")
    statement: str = Field(min_length=5, max_length=500)
    evidence_required: str = Field(min_length=3, max_length=500)


class GoalContract(FrozenPacket):
    objective: str = Field(min_length=5, max_length=2000)
    requirements: tuple[Requirement, ...] = Field(min_length=1, max_length=12)
    non_goals: tuple[str, ...] = Field(default=(), max_length=12)
    completion_test: str = Field(min_length=5, max_length=1000)


class EvidenceRef(FrozenPacket):
    id: str
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    excerpt: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_lines(self) -> EvidenceRef:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class ContextPacket(FrozenPacket):
    repository_fingerprint: str
    evidence: tuple[EvidenceRef, ...]
    gaps: tuple[str, ...] = ()
    budget_chars: int = Field(gt=0)
    used_chars: int = Field(ge=0)
    truncated: bool

    @model_validator(mode="after")
    def validate_budget(self) -> ContextPacket:
        if self.used_chars > self.budget_chars:
            raise ValueError("context packet exceeds its declared budget")
        return self


class PlanStep(FrozenPacket):
    order: int = Field(ge=1, le=20)
    action: str = Field(min_length=3, max_length=500)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    acceptance_test: str = Field(min_length=3, max_length=500)


class PlanDraft(FrozenPacket):
    summary: str = Field(min_length=5, max_length=1000)
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=12)
    files: tuple[str, ...] = Field(
        min_length=1,
        max_length=20,
        description="Exact writable replacement targets only; exclude files merely read or tested.",
    )
    test_ids: tuple[str, ...] = Field(min_length=1, max_length=10)
    risks: tuple[str, ...] = Field(default=(), max_length=12)


class FileReplacement(FrozenPacket):
    path: str
    expected_sha256: str
    content: str = Field(min_length=1, max_length=30000)

    @field_validator("expected_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
        return value


class PatchDraft(FrozenPacket):
    summary: str = Field(min_length=5, max_length=1000)
    replacements: tuple[FileReplacement, ...] = Field(min_length=1, max_length=10)
    test_ids: tuple[str, ...] = Field(min_length=1, max_length=10)
    rationale: str = Field(min_length=5, max_length=2000)


class RequirementResult(FrozenPacket):
    requirement_id: str
    status: Literal["proved", "unproved", "contradicted"]
    evidence: tuple[str, ...] = ()
    explanation: str = Field(min_length=3, max_length=1000)


class ReviewDraft(FrozenPacket):
    requirement_results: tuple[RequirementResult, ...] = Field(min_length=1)
    findings: tuple[str, ...] = ()
    next_action: str = Field(min_length=3, max_length=1000)


class TestReceipt(FrozenPacket):
    command_id: str
    argv: tuple[str, ...]
    exit_code: int
    duration_ms: int = Field(ge=0)
    stdout: str
    stderr: str


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REVISE = "revise"


class Approval(FrozenPacket):
    decision: ApprovalDecision
    packet_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    repository_fingerprint: str
    feedback: str = Field(default="", max_length=2000)


class PacketEnvelope(FrozenPacket):
    kind: str
    task_id: str
    thread_id: str
    iteration: int = Field(ge=0)
    repository_fingerprint: str
    payload: dict[str, Any]
    packet_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def canonical_hash(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def envelope(
    *,
    kind: str,
    task_id: str,
    thread_id: str,
    iteration: int,
    repository_fingerprint: str,
    payload: BaseModel | dict[str, Any],
) -> PacketEnvelope:
    payload_dict = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    unsigned = {
        "kind": kind,
        "task_id": task_id,
        "thread_id": thread_id,
        "iteration": iteration,
        "repository_fingerprint": repository_fingerprint,
        "payload": payload_dict,
    }
    return PacketEnvelope(**unsigned, packet_hash=canonical_hash(unsigned))
