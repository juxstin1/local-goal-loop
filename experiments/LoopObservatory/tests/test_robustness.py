"""Added after initial CORE ticket, from independent failing probes."""
import json
import pytest
from trace_reader import load_trace
from trace_metrics import summarize

@pytest.mark.parametrize("row,expected", [
    ({"response": []}, {"tokens": 0, "output": ""}),
    ({"response": {"usage_metadata": "bad"}}, {"tokens": 0}),
    ({"response": {"response_metadata": []}}, {"tokens": 0}),
    ({"response": {"tool_calls": [17]}}, {"output": ""}),
    ({"input": {"tests": 42}}, {"status": "ok"}),
    ({"input": {"tests": [{"exit_code": "failed"}]}}, {"status": "ok"}),
    ({"role": ["plan"], "attempt": "two"}, {"role": "unknown", "attempt": 1}),
    ({"response": {"usage_metadata": {"output_tokens": -1}, "response_metadata": {"token_usage": {"completion_tokens": 13}}}}, {"tokens": 13}),
    ({"response": {"usage_metadata": {"output_tokens": 0}, "response_metadata": {"token_usage": {"completion_tokens": 13}}}}, {"tokens": 0}),
    ({"response": {"content": [{"text": "hello"}]}}, {"output": ""}),
])
def test_malformed_optional_fields(tmp_path, row, expected):
    path = tmp_path / "trace.jsonl"
    path.write_text(json.dumps(row), encoding="utf-8")
    events, warnings = load_trace(path)
    assert not warnings
    assert {key: events[0][key] for key in expected} == expected
    json.dumps(summarize(events))
