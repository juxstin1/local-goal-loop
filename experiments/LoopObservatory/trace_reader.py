"""Qwen-owned implementation: parse local graph-engineer JSONL traces per BRIEF.md."""
import json
import os


def load_trace(path):
    """Load a UTF-8 JSONL trace file, returning (events, warnings)."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    events = []
    warnings = []
    with open(path, 'r', encoding='utf-8-sig') as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                warnings.append(f"Malformed JSON at line {line_num}")
                continue
            if not isinstance(row, dict):
                warnings.append(f"Non-object row at line {line_num}")
                continue
            role = row.get("role")
            if not isinstance(role, str):
                role = "unknown"
            attempt_raw = row.get("attempt")
            if isinstance(attempt_raw, int) and attempt_raw > 0:
                attempt = attempt_raw
            else:
                attempt = 1
            event = {
                "line": line_num,
                "role": role,
                "attempt": attempt,
                "tokens": 0,
                "status": "ok",
                "output": ""
            }
            response = row.get("response")
            if isinstance(response, dict):
                usage_metadata = response.get("usage_metadata")
                if isinstance(usage_metadata, dict):
                    output_tokens = usage_metadata.get("output_tokens")
                else:
                    output_tokens = None
                response_metadata = response.get("response_metadata")
                if isinstance(response_metadata, dict):
                    token_usage = response_metadata.get("token_usage")
                else:
                    token_usage = None
                if output_tokens is not None and isinstance(output_tokens, int) and output_tokens >= 0:
                    event["tokens"] = output_tokens
                elif token_usage is not None and isinstance(token_usage, dict):
                    completion_tokens = token_usage.get("completion_tokens")
                    if isinstance(completion_tokens, int) and completion_tokens >= 0:
                        event["tokens"] = completion_tokens
                if response.get("tool_calls") and isinstance(response["tool_calls"], list) and len(response["tool_calls"]) > 0:
                    tool_call = response["tool_calls"][0]
                    if isinstance(tool_call, dict):
                        args = tool_call.get("args", {})
                        if isinstance(args, dict):
                            event["output"] = json.dumps(args, indent=2)
                elif response.get("content") and isinstance(response["content"], str):
                    event["output"] = response["content"]
            if row.get("error") or row.get("error_type"):
                event["status"] = "error"
                event["output"] = row.get("error") or row.get("error_type")
            elif row.get("input") and isinstance(row["input"], dict) and isinstance(row["input"].get("tests"), list):
                for test in row["input"]["tests"]:
                    if isinstance(test, dict) and isinstance(test.get("exit_code"), int) and test.get("exit_code") != 0:
                        event["status"] = "test-failed"
                        break
            events.append(event)
    return events, warnings
