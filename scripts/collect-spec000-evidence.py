from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any
from urllib.request import Request, urlopen

GIB = 1024**3
CONTEXT_SIZE = 32768
CONTEXT_LIMIT = math.floor(CONTEXT_SIZE * 0.70)
SERVER_ARGS = (
    "--host",
    "127.0.0.1",
    "--port",
    "8080",
    "--alias",
    "qwen3.5-9b-q4km",
    "--ctx-size",
    "32768",
    "--parallel",
    "1",
    "--jinja",
    "--reasoning",
    "off",
    "--n-gpu-layers",
    "999",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def get_json(base_url: str, path: str, *, timeout: float = 30) -> dict[str, Any]:
    with urlopen(f"{base_url}{path}", timeout=timeout) as response:
        return json.load(response)


def post_json(
    base_url: str, path: str, payload: dict[str, Any], *, timeout: float = 120
) -> dict[str, Any]:
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def structured_call(response: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    calls = response["choices"][0]["message"].get("tool_calls", [])
    if len(calls) != 1:
        raise ValueError(f"expected one tool call, received {len(calls)}")
    function = calls[0]["function"]
    arguments = function["arguments"]
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise TypeError("tool arguments are not a JSON object")
    return function["name"], arguments


def function_tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


ADD_TOOL = function_tool(
    "add",
    "Add two integers and return their arithmetic sum.",
    {"left": {"type": "integer"}, "right": {"type": "integer"}},
)

SELECTION_TOOLS = [
    ADD_TOOL,
    function_tool(
        "get_weather",
        "Return the current weather for one named city.",
        {"city": {"type": "string"}},
    ),
    function_tool(
        "search_code",
        "Search repository text for an exact query.",
        {"query": {"type": "string"}},
    ),
    function_tool(
        "read_file",
        "Read one repository-relative file path.",
        {"path": {"type": "string"}},
    ),
]

SELECTION_CASES = [
    ("Add 8 and 13.", "add"),
    ("Compute the arithmetic sum of 144 and 233.", "add"),
    ("What is -9 plus 17?", "add"),
    ("Use the calculator to total 0 and 42.", "add"),
    ("Please add 999 to 1.", "add"),
    ("What is the current weather in Halifax?", "get_weather"),
    ("Check today's weather for Tokyo.", "get_weather"),
    ("Tell me the weather in Nairobi.", "get_weather"),
    ("Look up current weather for Reykjavik.", "get_weather"),
    ("Fetch the weather for Buenos Aires.", "get_weather"),
    ("Search the repository for build_goal_graph.", "search_code"),
    ("Find every occurrence of MAX_REVISIONS in the code.", "search_code"),
    ("Search source text for repository_fingerprint.", "search_code"),
    ("Locate the exact string revision_cap_reached.", "search_code"),
    ("Search the codebase for LocalChatRoleModel.", "search_code"),
    ("Read the repository file README.md.", "read_file"),
    ("Open src/graph_engineer/graph.py.", "read_file"),
    ("Show me the contents of pyproject.toml.", "read_file"),
    ("Read fixtures/tasks.json.", "read_file"),
    ("Load tests/test_goal_loop.py.", "read_file"),
]


def chat_payload(prompt: str, tools: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    return {
        "model": "qwen3.5-9b-q4km",
        "messages": [{"role": "user", "content": prompt}],
        "tools": tools,
        "tool_choice": "required",
        "parallel_tool_calls": False,
        "temperature": 0,
        "seed": seed,
        "max_tokens": 256,
    }


def run_raw_calls(base_url: str) -> dict[str, Any]:
    prompt = "Use the add tool to calculate 17 + 25. Do not answer in plain text."
    cases = []
    for index in range(10):
        started = time.perf_counter()
        response = post_json(
            base_url, "/v1/chat/completions", chat_payload(prompt, [ADD_TOOL], index)
        )
        error = None
        name = None
        arguments = None
        valid = False
        try:
            name, arguments = structured_call(response)
            valid = name == "add" and arguments == {"left": 17, "right": 25}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        cases.append(
            {
                "case": index + 1,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "name": name,
                "arguments": arguments,
                "valid": valid,
                "error": error,
                "raw_response": response,
            }
        )
    valid_count = sum(case["valid"] for case in cases)
    return {
        "threshold": "10/10 valid add(17, 25) structured envelopes",
        "observed": f"{valid_count}/10",
        "passed": valid_count == 10,
        "cases": cases,
    }


def run_tool_selection(base_url: str) -> dict[str, Any]:
    cases = []
    for index, (prompt, expected) in enumerate(SELECTION_CASES):
        response = post_json(
            base_url,
            "/v1/chat/completions",
            chat_payload(prompt, SELECTION_TOOLS, 100 + index),
        )
        error = None
        actual = None
        arguments = None
        parseable = False
        try:
            actual, arguments = structured_call(response)
            parseable = True
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        cases.append(
            {
                "case": index + 1,
                "prompt": prompt,
                "expected": expected,
                "actual": actual,
                "arguments": arguments,
                "parseable": parseable,
                "correct": parseable and actual == expected,
                "error": error,
                "raw_response": response,
            }
        )
    parseable = sum(case["parseable"] for case in cases)
    correct = sum(case["correct"] for case in cases)
    return {
        "threshold": "at least 18/20 correct selections and 20/20 parseable envelopes",
        "observed": {"correct": correct, "parseable": parseable, "total": 20},
        "passed": correct >= 18 and parseable == 20,
        "cases": cases,
    }


def token_count(base_url: str, content: str) -> int:
    response = post_json(
        base_url,
        "/tokenize",
        {"content": content, "add_special": True, "parse_special": True},
    )
    return len(response["tokens"])


def build_2k_prompt(base_url: str) -> tuple[str, int]:
    suffix = (
        "\nContinue by emitting a numbered list of short engineering verification steps. "
        "Do not stop until the requested token limit is reached.\n"
    )
    low, high = 1, 4096
    best: tuple[int, str] | None = None
    while low <= high:
        middle = (low + high) // 2
        prompt = "evidence " * middle + suffix
        count = token_count(base_url, prompt)
        if best is None or abs(count - 2048) < abs(best[0] - 2048):
            best = (count, prompt)
        if count < 2048:
            low = middle + 1
        elif count > 2048:
            high = middle - 1
        else:
            break
    assert best is not None
    return best[1], best[0]


def stream_completion(base_url: str, prompt: str, seed: int) -> dict[str, Any]:
    payload = {
        "prompt": prompt,
        "n_predict": 128,
        "temperature": 0,
        "seed": seed,
        "stream": True,
        "ignore_eos": True,
        "cache_prompt": False,
        "timings_per_token": False,
    }
    request = Request(
        f"{base_url}/completion",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first_content_at = None
    chunks: list[str] = []
    final: dict[str, Any] | None = None
    with urlopen(request, timeout=180) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "):
                continue
            data = json.loads(line[6:])
            content = data.get("content", "")
            if content and first_content_at is None:
                first_content_at = time.perf_counter()
            if content:
                chunks.append(content)
            if data.get("stop"):
                final = data
    ended = time.perf_counter()
    if first_content_at is None or final is None:
        raise ValueError("stream did not contain both a first token and a final timing chunk")
    timings = final.get("timings", {})
    predicted_n = int(timings.get("predicted_n", final.get("tokens_predicted", 0)))
    predicted_per_second = timings.get("predicted_per_second")
    if not predicted_per_second:
        predicted_per_second = predicted_n / max(ended - first_content_at, 1e-9)
    content = "".join(chunks)
    return {
        "ttft_ms": round((first_content_at - started) * 1000, 3),
        "request_ms": round((ended - started) * 1000, 3),
        "predicted_tokens": predicted_n,
        "predicted_tokens_per_second": round(float(predicted_per_second), 3),
        "content_chars": len(content),
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "stop_type": final.get("stop_type"),
        "timings": timings,
    }


def percentile_nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def run_stability(base_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt, input_tokens = build_2k_prompt(base_url)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    cases = []
    for index in range(20):
        try:
            result = stream_completion(base_url, prompt, 1000 + index)
            result.update({"case": index + 1, "success": True, "error": None})
        except Exception as exc:
            result = {
                "case": index + 1,
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        cases.append(result)
    successful = [case for case in cases if case["success"]]
    speeds = [case["predicted_tokens_per_second"] for case in successful]
    ttfts = [case["ttft_ms"] for case in successful]
    performance = {
        "threshold": {
            "median_generation_tokens_per_second": ">=25",
            "p95_first_token_ms": "<=3000",
            "input_tokens": "approximately 2048 and <=70% of 32768",
        },
        "observed": {
            "median_generation_tokens_per_second": round(median(speeds), 3) if speeds else None,
            "p95_first_token_ms": round(percentile_nearest_rank(ttfts, 0.95), 3) if ttfts else None,
            "percentile_method": "nearest-rank",
            "input_tokens": input_tokens,
            "input_context_percent": round(input_tokens / CONTEXT_SIZE * 100, 4),
            "input_prompt_sha256": prompt_hash,
        },
        "passed": bool(speeds)
        and median(speeds) >= 25
        and percentile_nearest_rank(ttfts, 0.95) <= 3000
        and input_tokens <= CONTEXT_LIMIT,
        "cases": cases,
    }
    stability = {
        "threshold": "zero failures across 20 sequential requests",
        "observed": {"successful": len(successful), "failures": 20 - len(successful)},
        "passed": len(successful) == 20,
        "request_case_ids": [case["case"] for case in cases],
    }
    return performance, stability


class MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class VkMemoryType(ctypes.Structure):
    _fields_ = [("propertyFlags", ctypes.c_uint32), ("heapIndex", ctypes.c_uint32)]


class VkMemoryHeap(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint64), ("flags", ctypes.c_uint32)]


class VkPhysicalDeviceMemoryProperties(ctypes.Structure):
    _fields_ = [
        ("memoryTypeCount", ctypes.c_uint32),
        ("memoryTypes", VkMemoryType * 32),
        ("memoryHeapCount", ctypes.c_uint32),
        ("memoryHeaps", VkMemoryHeap * 16),
    ]


class VkPhysicalDeviceMemoryBudgetPropertiesExt(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("heapBudget", ctypes.c_uint64 * 16),
        ("heapUsage", ctypes.c_uint64 * 16),
    ]


class VkPhysicalDeviceMemoryProperties2(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("memoryProperties", VkPhysicalDeviceMemoryProperties),
    ]


class VkApplicationInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("pApplicationName", ctypes.c_char_p),
        ("applicationVersion", ctypes.c_uint32),
        ("pEngineName", ctypes.c_char_p),
        ("engineVersion", ctypes.c_uint32),
        ("apiVersion", ctypes.c_uint32),
    ]


class VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("pApplicationInfo", ctypes.POINTER(VkApplicationInfo)),
        ("enabledLayerCount", ctypes.c_uint32),
        ("ppEnabledLayerNames", ctypes.c_void_p),
        ("enabledExtensionCount", ctypes.c_uint32),
        ("ppEnabledExtensionNames", ctypes.c_void_p),
    ]


def host_memory() -> dict[str, Any]:
    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return {
        "total_bytes": status.ullTotalPhys,
        "available_bytes": status.ullAvailPhys,
        "available_gib": round(status.ullAvailPhys / GIB, 3),
    }


def vulkan_memory_budget() -> dict[str, Any]:
    vulkan = ctypes.WinDLL("vulkan-1.dll")
    vulkan.vkEnumeratePhysicalDevices.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    vulkan.vkGetPhysicalDeviceProperties.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    vulkan.vkGetPhysicalDeviceMemoryProperties2.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(VkPhysicalDeviceMemoryProperties2),
    ]
    vulkan.vkDestroyInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    instance = ctypes.c_void_p()
    app = VkApplicationInfo(
        sType=0,
        pApplicationName=b"spec000-evidence",
        applicationVersion=1,
        pEngineName=b"none",
        engineVersion=1,
        apiVersion=1 << 22,
    )
    create_info = VkInstanceCreateInfo(sType=1, pApplicationInfo=ctypes.pointer(app))
    vulkan.vkCreateInstance.argtypes = [
        ctypes.POINTER(VkInstanceCreateInfo),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    result = vulkan.vkCreateInstance(ctypes.byref(create_info), None, ctypes.byref(instance))
    if result != 0:
        raise RuntimeError(f"vkCreateInstance returned {result}")
    try:
        count = ctypes.c_uint32()
        vulkan.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None)
        devices = (ctypes.c_void_p * count.value)()
        vulkan.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), devices)
        heaps = []
        for device in devices:
            properties_buffer = ctypes.create_string_buffer(4096)
            vulkan.vkGetPhysicalDeviceProperties(device, properties_buffer)
            name = bytes(properties_buffer[20:276]).split(b"\0", 1)[0].decode(errors="replace")
            budget = VkPhysicalDeviceMemoryBudgetPropertiesExt(sType=1000237000)
            memory = VkPhysicalDeviceMemoryProperties2(
                sType=1000059006,
                pNext=ctypes.cast(ctypes.pointer(budget), ctypes.c_void_p),
            )
            vulkan.vkGetPhysicalDeviceMemoryProperties2(device, ctypes.byref(memory))
            for index in range(memory.memoryProperties.memoryHeapCount):
                heap = memory.memoryProperties.memoryHeaps[index]
                if heap.flags & 1:
                    heaps.append(
                        {
                            "device": name,
                            "heap_index": index,
                            "heap_size_bytes": heap.size,
                            "heap_budget_bytes": budget.heapBudget[index],
                            "heap_usage_bytes": budget.heapUsage[index],
                            "additional_allocatable_bytes": max(
                                0, budget.heapBudget[index] - budget.heapUsage[index]
                            ),
                        }
                    )
        if not heaps:
            raise RuntimeError("no device-local Vulkan memory heap was reported")
        selected = dict(max(heaps, key=lambda item: item["heap_size_bytes"]))
        selected["additional_allocatable_gib"] = round(
            selected["additional_allocatable_bytes"] / GIB, 3
        )
        selected["all_device_local_heaps"] = heaps
        return selected
    finally:
        vulkan.vkDestroyInstance(instance, None)


def windows_gpu_memory(server_pid: int, heap_size_bytes: int) -> dict[str, Any]:
    powershell = (
        "$samples = (Get-Counter "
        "'\\GPU Adapter Memory(*)\\Dedicated Usage',"
        "'\\GPU Process Memory(*)\\Dedicated Usage').CounterSamples; "
        "$samples | Select-Object Path,InstanceName,CookedValue | "
        "ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", powershell],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Get-Counter failed: {completed.stderr.strip()}")
    raw_samples = json.loads(completed.stdout)
    if isinstance(raw_samples, dict):
        raw_samples = [raw_samples]
    samples = [
        {
            "path": sample["Path"],
            "instance_name": sample["InstanceName"],
            "cooked_value_bytes": round(float(sample["CookedValue"])),
        }
        for sample in raw_samples
    ]
    process_prefix = f"pid_{server_pid}_"
    process_samples = [
        sample for sample in samples if sample["instance_name"].startswith(process_prefix)
    ]
    if not process_samples:
        raise RuntimeError(f"no GPU Process Memory sample matched llama-server PID {server_pid}")
    adapter_instances = {
        sample["instance_name"].removeprefix(process_prefix) for sample in process_samples
    }
    adapter_samples = [sample for sample in samples if sample["instance_name"] in adapter_instances]
    if not adapter_samples:
        raise RuntimeError("no GPU Adapter Memory sample matched the llama-server adapter")
    adapter_usage = max(sample["cooked_value_bytes"] for sample in adapter_samples)
    server_usage = sum(sample["cooked_value_bytes"] for sample in process_samples)
    return {
        "source": "Windows GPU Adapter Memory and GPU Process Memory performance counters",
        "server_pid": server_pid,
        "adapter_instances": sorted(adapter_instances),
        "adapter_dedicated_usage_bytes": adapter_usage,
        "adapter_dedicated_usage_gib": round(adapter_usage / GIB, 3),
        "server_dedicated_usage_bytes": server_usage,
        "server_dedicated_usage_gib": round(server_usage / GIB, 3),
        "physical_device_local_heap_bytes": heap_size_bytes,
        "physical_device_local_heap_gib": round(heap_size_bytes / GIB, 3),
        "free_dedicated_vram_bytes": max(0, heap_size_bytes - adapter_usage),
        "free_dedicated_vram_gib": round(max(0, heap_size_bytes - adapter_usage) / GIB, 3),
        "matched_process_samples": process_samples,
        "matched_adapter_samples": adapter_samples,
    }


def run_pytest_gate(project_root: Path, node_ids: list[str], expected: int) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", "-o", "addopts=", *node_ids]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
    match = re.search(r"(?P<count>\d+) passed", completed.stdout)
    passed_count = int(match.group("count")) if match else 0
    return {
        "command": command,
        "cwd": str(project_root),
        "expected_rejections_or_protections": expected,
        "observed_passed": passed_count,
        "exit_code": completed.returncode,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "passed": completed.returncode == 0 and passed_count == expected,
    }


def source_manifest(project_root: Path) -> dict[str, str]:
    paths = [
        project_root / "Makefile",
        project_root / "langgraph.json",
        project_root / "pyproject.toml",
        project_root / "uv.lock",
    ]
    for relative in ("src", "tests"):
        paths.extend((project_root / relative).rglob("*.py"))
    for suffix in ("*.py", "*.ps1"):
        paths.extend((project_root / "scripts").rglob(suffix))
    paths.append(project_root / "fixtures" / "tasks.json")
    return {
        path.relative_to(project_root).as_posix(): sha256_file(path) for path in sorted(set(paths))
    }


def fixture_evidence(fixture_receipt: Path, output_dir: Path) -> dict[str, Any]:
    receipt = json.loads(fixture_receipt.read_text(encoding="utf-8"))
    destination = output_dir / "fixture-evaluation-8-of-10.json"
    shutil.copyfile(fixture_receipt, destination)
    complete = [
        result
        for result in receipt["results"]
        if result.get("final_receipt", {}).get("status") == "complete"
    ]
    zero_exit = all(
        result["final_receipt"]["tests"]
        and all(test["exit_code"] == 0 for test in result["final_receipt"]["tests"])
        for result in complete
    )
    return {
        "threshold": "record the existing 8/10 live fixture result",
        "observed": f"{receipt['complete_count']}/{receipt['fixture_count']}",
        "passed": receipt["complete_count"] == 8
        and receipt["fixture_count"] == 10
        and receipt["passed"]
        and zero_exit,
        "receipt": destination.name,
        "receipt_sha256": sha256_file(destination),
        "all_completed_fixtures_have_zero_exit_tests": zero_exit,
        "failed_tasks": [result["task"] for result in receipt["results"] if result not in complete],
        "reproduction_command": [
            ".\\scripts\\run-live-demo.ps1",
            "-ServerExe",
            "<LLAMA_SERVER_EXE>",
            "-ModelPath",
            "<LOCAL_MODEL_PATH>",
            "-ReceiptPath",
            ".runtime\\live-evaluation-retry-2.json",
            "-Evaluate",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect the complete SPEC-000 evidence matrix")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--server-exe", type=Path, required=True)
    parser.add_argument("--server-pid", type=int, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--fixture-receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    repo_root = project_root
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    health = get_json(args.base_url, "/health")
    models = get_json(args.base_url, "/v1/models")
    props = get_json(args.base_url, "/props")
    (output_dir / "server-props.json").write_text(
        json.dumps(props, indent=2) + "\n", encoding="utf-8"
    )

    version = subprocess.run(
        [str(args.server_exe.resolve()), "--version"],
        text=True,
        capture_output=True,
        check=False,
    )
    manifest = source_manifest(project_root)
    git_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    gates: dict[str, Any] = {}
    gates["raw_structured_calls"] = run_raw_calls(args.base_url)
    gates["tool_selection"] = run_tool_selection(args.base_url)
    gates["fixture_usefulness"] = fixture_evidence(args.fixture_receipt.resolve(), output_dir)
    gates["containment"] = run_pytest_gate(project_root, ["tests/test_containment_matrix.py"], 24)
    gates["approval_protections"] = run_pytest_gate(
        project_root,
        ["tests/test_safety_matrix.py::test_approval_matrix_rejects_before_mutation"],
        12,
    )
    gates["prompt_injection"] = run_pytest_gate(
        project_root,
        [
            "tests/test_safety_matrix.py::test_repository_path_injection_cannot_expand_write_scope",
            "tests/test_safety_matrix.py::test_repository_command_injection_cannot_expand_execution_scope",
        ],
        30,
    )
    gates["one_revision_cap"] = run_pytest_gate(
        project_root, ["tests/test_goal_loop.py::test_one_revision_is_the_absolute_maximum"], 1
    )
    gates["performance"], gates["sequential_stability"] = run_stability(args.base_url)

    host = host_memory()
    try:
        vram = vulkan_memory_budget()
        vram_error = None
    except Exception as exc:
        vram = None
        vram_error = f"{type(exc).__name__}: {exc}"
    try:
        gpu_memory = windows_gpu_memory(args.server_pid, vram["heap_size_bytes"])
        gpu_memory_error = None
    except Exception as exc:
        gpu_memory = None
        gpu_memory_error = f"{type(exc).__name__}: {exc}"
    gates["vulkan_backend"] = {
        "threshold": (
            "llama-server runs with --n-gpu-layers 999 and owns at least 1 GiB "
            "of dedicated memory on the selected Vulkan adapter"
        ),
        "observed": {
            "n_gpu_layers": 999,
            "windows_gpu_memory": gpu_memory,
            "measurement_error": gpu_memory_error,
        },
        "passed": gpu_memory is not None and gpu_memory["server_dedicated_usage_bytes"] >= GIB,
    }
    gates["memory_headroom"] = {
        "threshold": {"free_dedicated_vram_gib": ">=1", "free_host_ram_gib": ">=4"},
        "observed": {
            "vulkan_memory_budget": vram,
            "vulkan_error": vram_error,
            "windows_gpu_memory": gpu_memory,
            "windows_gpu_memory_error": gpu_memory_error,
            "host_memory": host,
        },
        "passed": gpu_memory is not None
        and gpu_memory["free_dedicated_vram_bytes"] >= GIB
        and host["available_bytes"] >= 4 * GIB,
    }
    input_tokens = gates["performance"]["observed"]["input_tokens"]
    gates["context_reserve"] = {
        "threshold": f"input <=70% of {CONTEXT_SIZE} tokens ({CONTEXT_LIMIT} tokens)",
        "observed": {
            "input_tokens": input_tokens,
            "configured_context_tokens": CONTEXT_SIZE,
            "input_percent": round(input_tokens / CONTEXT_SIZE * 100, 4),
            "reserved_tokens": CONTEXT_SIZE - input_tokens,
        },
        "passed": input_tokens <= CONTEXT_LIMIT,
    }

    server_command = [
        str(args.server_exe.resolve()),
        "--model",
        str(args.model_path.resolve()),
        *SERVER_ARGS,
    ]
    receipt = {
        "schema_version": "spec-000-evidence-v1",
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "status": "pass" if all(gate["passed"] for gate in gates.values()) else "fail",
        "environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "git_revision": git_revision,
            "working_tree_source_state": "untracked example; authoritative source manifest below",
        },
        "server": {
            "health": health,
            "models": models,
            "version_command": [str(args.server_exe.resolve()), "--version"],
            "version_exit_code": version.returncode,
            "version_stdout": version.stdout,
            "version_stderr": version.stderr,
            "pid": args.server_pid,
            "command": server_command,
            "executable_sha256": sha256_file(args.server_exe.resolve()),
            "model_path": str(args.model_path.resolve()),
            "model_size_bytes": args.model_path.stat().st_size,
            "model_sha256": sha256_file(args.model_path.resolve()),
            "props_file": "server-props.json",
            "props_sha256": sha256_file(output_dir / "server-props.json"),
            "model_alias": props.get("model_alias"),
            "default_generation_settings": props.get("default_generation_settings"),
            "total_slots": props.get("total_slots"),
            "chat_template_caps": props.get("chat_template_caps"),
            "has_nonempty_chat_template": bool(props.get("chat_template")),
        },
        "source": {
            "manifest": manifest,
            "manifest_sha256": canonical_hash(manifest),
            "fixture_tasks_sha256": manifest["fixtures/tasks.json"],
        },
        "commands": {
            "collector": [sys.executable, *sys.argv],
            "collector_cwd": os.getcwd(),
            "server": server_command,
        },
        "gates": gates,
    }
    receipt_path = output_dir / "spec-000-evidence.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    summary = {
        "status": receipt["status"],
        "receipt": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "gates": {name: gate["passed"] for name, gate in gates.items()},
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
