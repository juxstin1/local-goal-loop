import copy
import json

import pytest

from trace_reader import load_trace
from trace_metrics import summarize


def write_rows(tmp_path, rows):
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    return path


def test_reads_real_response_shape_and_preserves_source(tmp_path):
    source = "def greet():\n    return 'Olá ⚓'\n"
    path = write_rows(tmp_path, [{"role": "patch", "attempt": 2, "response": {
        "tool_calls": [{"args": {"replacements": [{"path": "main.py", "content": source}]}}],
        "usage_metadata": {"output_tokens": 43}}}])
    events, warnings = load_trace(path)
    assert warnings == []
    assert len(events) == 1
    event = events[0]
    assert (event["line"], event["role"], event["attempt"], event["tokens"], event["status"]) == (1, "patch", 2, 43, "ok")
    assert json.loads(event["output"])["replacements"][0]["content"] == source


def test_bom_blanks_bad_rows_and_original_line_numbers(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text('\ufeff\n{broken\n[]\n\n{"role":"review","response":{"content":"hello"}}\n', encoding="utf-8")
    events, warnings = load_trace(path)
    assert len(events) == 1
    assert events[0]["line"] == 5
    assert events[0]["output"] == "hello"
    assert len(warnings) == 2
    assert "2" in warnings[0] and "3" in warnings[1]


def test_errors_and_test_failures_are_distinct(tmp_path):
    rows = [
        {"role": "patch", "error_type": "ServerError", "error": "bad JSON"},
        {"role": "review", "input": {"tests": [{"exit_code": 1}]}, "response": {}},
        {"role": "review", "input": {"tests": [{"exit_code": 0}]}, "response": {}},
    ]
    events, warnings = load_trace(write_rows(tmp_path, rows))
    assert [e["status"] for e in events] == ["error", "test-failed", "ok"]
    assert "bad JSON" in events[0]["output"]
    assert warnings == []


def test_optional_fields_and_token_fallback(tmp_path):
    rows = [{}, {"role": "plan", "response": {"response_metadata": {
        "token_usage": {"completion_tokens": 12}}}},
        {"role": None, "attempt": -1, "response": None, "input": None},
        {"response": {"usage_metadata": {"output_tokens": -50}, "tool_calls": []}}]
    events, warnings = load_trace(write_rows(tmp_path, rows))
    assert len(events) == 4 and not warnings
    assert events[0]["role"] == "unknown"
    assert events[0]["output"] == ""
    assert events[1]["tokens"] == 12
    assert events[2]["attempt"] == 1
    assert events[3]["tokens"] == 0


def test_missing_file_is_not_silent(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_trace(tmp_path / "absent.jsonl")


def test_summary_counts_without_mutation():
    events = [
        {"role": "plan", "status": "ok", "attempt": 1, "tokens": 10},
        {"role": "patch", "status": "error", "attempt": 2, "tokens": 0},
        {"role": "review", "status": "test-failed", "attempt": 1, "tokens": 7},
    ]
    before = copy.deepcopy(events)
    assert summarize(events) == {"calls": 3, "errors": 1, "failed_tests": 1,
        "repairs": 1, "output_tokens": 17, "roles": {"plan": 1, "patch": 1, "review": 1}}
    assert events == before
    assert summarize([]) == {"calls": 0, "errors": 0, "failed_tests": 0,
        "repairs": 0, "output_tokens": 0, "roles": {}}
