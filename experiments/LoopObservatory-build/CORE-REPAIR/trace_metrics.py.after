"""Qwen-owned implementation: calculate recorded-call metrics per BRIEF.md."""


def summarize(events):
    calls = len(events)
    errors = sum(1 for e in events if e["status"] == "error")
    failed_tests = sum(1 for e in events if e["status"] == "test-failed")
    repairs = sum(1 for e in events if e["attempt"] > 1)
    output_tokens = sum(e["tokens"] for e in events)
    roles = {}
    for e in events:
        role = e["role"]
        roles[role] = roles.get(role, 0) + 1
    return {
        "calls": calls,
        "errors": errors,
        "failed_tests": failed_tests,
        "repairs": repairs,
        "output_tokens": output_tokens,
        "roles": roles
    }
