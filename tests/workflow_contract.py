"""Shared workflow-contract helpers, used by every template test module.

The security properties asserted here -- SHA-pinned actions, a checkout that does not
persist credentials -- are the same contract regardless of which template is under test,
so they have one implementation rather than one per suite.

Not named `test_*`, so pytest imports it without collecting it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+)(?P<rest>.*)$")
PINNED_REF = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s*#\s*v\d+(\.\d+)*$")


def load(path: Path) -> dict:
    """Parse a workflow, mapping YAML 1.1's boolean `on` key back to "on"."""
    import yaml

    workflow = yaml.safe_load(path.read_text())
    if True in workflow:
        workflow["on"] = workflow.pop(True)
    return workflow


def uses_matches(path: Path) -> list[re.Match]:
    return [match for line in path.read_text().splitlines() if (match := USES_LINE.match(line))]


def action_pins(path: Path) -> list[tuple[str, str]]:
    """Every (action, sha) pin in a workflow, one entry per `uses:` line.

    A list rather than a mapping: a file pinning the same action at two different SHAs
    has to surface both, and a dict would keep only the last.
    """
    return [
        (action, sha)
        for match in uses_matches(path)
        for action, _, sha in [match["ref"].partition("@")]
    ]


def assert_every_action_is_pinned(path: Path) -> None:
    matches = uses_matches(path)
    assert matches, f"{path.name} uses no actions"
    for match in matches:
        assert PINNED_REF.match(match["ref"]), match["ref"]
        assert VERSION_COMMENT.match(match["rest"]), f"{match['ref']} needs a `# vX.Y.Z` comment"


def assert_checkout_does_not_persist_credentials(job: dict) -> None:
    checkout = job["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False


def assert_triggers(on: dict) -> None:
    """Every PR runs the check; pushes run on the default branch only."""
    assert set(on) == {"pull_request", "push"}
    assert on["pull_request"] is None, "no branch filter: every PR runs the check"
    assert list(on["push"]) == ["branches"], "push runs on the default branch only"
    assert len(on["push"]["branches"]) == 1


def assert_read_only_permissions(workflow: dict, job: dict) -> None:
    assert workflow["permissions"] == {"contents": "read"}
    assert "permissions" not in job, "no job widens the token"
