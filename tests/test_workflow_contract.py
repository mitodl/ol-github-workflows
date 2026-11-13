"""Tests for the shared workflow-contract helpers themselves.

`action_pins` in particular has to keep every pin on a file rather than the last one
per action, or `test_all_templates_pin_the_same_commit_per_action` stops seeing an
action pinned twice at different SHAs inside a single workflow.
"""

from __future__ import annotations

from pathlib import Path

from workflow_contract import action_pins

CHECKOUT = "actions/checkout"
SHA_A = "3d3c42e5aac5ba805825da76410c181273ba90b1"
SHA_B = "0000000000000000000000000000000000000000"


def write(tmp_path: Path, *refs: str) -> Path:
    steps = "\n".join(f"      - uses: {ref} # v1.0.0" for ref in refs)
    path = tmp_path / "wf.yml"
    path.write_text(f"jobs:\n  j:\n    steps:\n{steps}\n")
    return path


def test_keeps_every_pin_not_the_last_one_per_action(tmp_path: Path) -> None:
    """One file, one action, two SHAs -- both must survive."""
    pins = action_pins(write(tmp_path, f"{CHECKOUT}@{SHA_A}", f"{CHECKOUT}@{SHA_B}"))
    assert pins == [(CHECKOUT, SHA_A), (CHECKOUT, SHA_B)]
    assert len({sha for _, sha in pins}) == 2, "within-file drift must stay visible"


def test_reads_each_action_and_sha(tmp_path: Path) -> None:
    pins = action_pins(write(tmp_path, f"{CHECKOUT}@{SHA_A}", f"astral-sh/setup-uv@{SHA_B}"))
    assert pins == [(CHECKOUT, SHA_A), ("astral-sh/setup-uv", SHA_B)]


def test_empty_for_a_workflow_using_no_actions(tmp_path: Path) -> None:
    path = tmp_path / "wf.yml"
    path.write_text("jobs:\n  j:\n    steps:\n      - run: echo hi\n")
    assert action_pins(path) == []
