from __future__ import annotations

from graph_engineer.model import WIRE_SCHEMAS
from graph_engineer.packets import GoalContract, Requirement, canonical_hash, envelope


def test_canonical_hash_is_order_independent_for_mappings() -> None:
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_envelope_hash_changes_with_iteration() -> None:
    goal = GoalContract(
        objective="Fix the fixture implementation.",
        requirements=(
            Requirement(
                id="REQ-001",
                statement="The fixture test must pass.",
                evidence_required="A zero-exit test receipt.",
            ),
        ),
        completion_test="The registered fixture test exits zero.",
    )
    first = envelope(
        kind="goal",
        task_id="task",
        thread_id="thread",
        iteration=0,
        repository_fingerprint="repo",
        payload=goal,
    )
    second = envelope(
        kind="goal",
        task_id="task",
        thread_id="thread",
        iteration=1,
        repository_fingerprint="repo",
        payload=goal,
    )

    assert first.packet_hash != second.packet_hash


def test_local_patch_wire_schema_leaves_constraints_to_host_validation() -> None:
    schema = WIRE_SCHEMAS["patch"].model_json_schema()
    serialized = str(schema)

    assert "maxLength" not in serialized
    assert "minLength" not in serialized
    assert "pattern" not in serialized


def test_review_wire_schema_constrains_status_to_lowercase_contract_values() -> None:
    schema = WIRE_SCHEMAS["review"].model_json_schema()
    serialized = str(schema)

    assert "'enum': ['proved', 'unproved', 'contradicted']" in serialized
