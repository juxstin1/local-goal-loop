from __future__ import annotations

from pathlib import Path

import pytest

from graph_engineer.context import build_context, resolve_inside


def test_context_packet_obeys_budget_and_reports_truncation(tmp_path: Path) -> None:
    (tmp_path / "large.py").write_text("x = 1\n" * 100, encoding="utf-8")

    packet = build_context(tmp_path, budget_chars=40)

    assert packet.used_chars <= 40
    assert packet.truncated is True
    assert packet.gaps == ("context truncated to configured character budget",)


@pytest.mark.parametrize(
    "relative",
    [
        "../secret.txt",
        "../../secret.txt",
        "sub/../../../secret.txt",
        "./../../secret.txt",
        "folder/../../secret.txt",
        "..\\secret.txt",
        "sub\\..\\..\\secret.txt",
        "C:/Windows/System32/drivers/etc/hosts",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "/Windows/System32/drivers/etc/hosts",
        "../../../Users/Public/secret.txt",
        "nested/../../../../outside.txt",
    ],
)
def test_resolve_inside_rejects_parent_traversal(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError, match="escapes repository"):
        resolve_inside(tmp_path, relative)


def test_context_excludes_runtime_noise(tmp_path: Path) -> None:
    (tmp_path / "visible.py").write_text("VISIBLE = True\n", encoding="utf-8")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "secret.py").write_text("HIDDEN = True\n", encoding="utf-8")

    packet = build_context(tmp_path, budget_chars=1000)

    assert [item.path for item in packet.evidence] == ["visible.py"]
