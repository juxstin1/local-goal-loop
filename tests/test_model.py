from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from graph_engineer.model import LocalChatRoleModel
from graph_engineer.packets import GoalContract


class FakeToolModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = responses
        self.bind_options: dict[str, Any] = {}
        self.invocations: list[list[Any]] = []

    def bind_tools(self, tools: list[type[Any]], **kwargs: Any) -> FakeToolModel:
        self.bind_options = {"tools": tools, **kwargs}
        return self

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.invocations.append(messages.copy())
        return self.responses.pop(0)


def test_local_model_repairs_a_missing_structured_call() -> None:
    valid_args = {
        "objective": "Fix the fixture.",
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "The registered test passes.",
                "evidence_required": "A zero-exit pytest receipt.",
            }
        ],
        "non_goals": [],
        "completion_test": "REQ-001 is proved by a zero-exit pytest receipt.",
    }
    fake = FakeToolModel(
        [
            AIMessage(content="I will explain instead of returning a packet."),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "GoalContract",
                        "args": valid_args,
                        "id": "goal-call",
                        "type": "tool_call",
                    }
                ],
            ),
        ]
    )
    model = LocalChatRoleModel(fake, packet_attempts=2)

    packet = model.invoke("goal", GoalContract, {"objective": "Fix the fixture."})

    assert packet.objective == "Fix the fixture."
    assert fake.bind_options["tool_choice"] == "required"
    assert fake.bind_options["parallel_tool_calls"] is False
    assert len(fake.invocations) == 2
    correction = fake.invocations[1][-1]
    assert isinstance(correction, HumanMessage)
    assert "exactly one structured call" in str(correction.content)
