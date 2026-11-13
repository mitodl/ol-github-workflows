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
TEMPLATE_DIR = ROOT / "workflow-templates"
OWN_WORKFLOWS = ROOT / ".github" / "workflows"

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


def action_pins(path: Path) -> dict[str, str]:
    """Map each action in a workflow to the commit SHA it is pinned at."""
    return {
        action: sha
        for match in uses_matches(path)
        for action, _, sha in [match["ref"].partition("@")]
    }


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
