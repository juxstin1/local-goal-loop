from __future__ import annotations

from graph_engineer.prompts import BASE_SYSTEM_PROMPT, ROLE_RULES, system_prompt


def test_every_role_prompt_has_the_stable_safety_prefix() -> None:
    for role in ROLE_RULES:
        assert system_prompt(role).startswith(BASE_SYSTEM_PROMPT)


def test_prompt_forbids_invented_completion_evidence() -> None:
    prompt = system_prompt("review")
    assert "Never invent" in prompt
    assert "Mark proved only" in prompt
