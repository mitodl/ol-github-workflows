"""Tests for the uv.lock revision workflow template.

Structural tests assert the properties the contract (docs/uv-lock-revision-contract.md)
requires, mirroring tests/test_templates.py for the autofix family. Behavioral tests run
the template's own `run:` script, taken from the YAML, against throwaway git repositories
whose lockfiles are correct, drifted, absent, and so on -- so the assertions cover the
script that actually ships rather than a copy of it.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "workflow-templates" / "uv-lock-revision.yml"
AUTOFIX_TEMPLATES = sorted((ROOT / "workflow-templates").glob("autofix-*.yml"))
JOB_ID = "uv-lock-revision"
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+)(?P<rest>.*)$")
PINNED_REF = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s*#\s*v\d+(\.\d+)*$")


def load(path: Path) -> dict:
    """Parse a workflow, mapping YAML 1.1's boolean `on` key back to "on"."""
    workflow = yaml.safe_load(path.read_text())
    if True in workflow:
        workflow["on"] = workflow.pop(True)
    return workflow


def the_job(workflow: dict) -> dict:
    jobs = workflow["jobs"]
    assert list(jobs) == [JOB_ID], f"the template defines exactly one job, `{JOB_ID}`"
    return jobs[JOB_ID]


def check_script() -> str:
    steps = the_job(load(TEMPLATE))["steps"]
    return next(step for step in steps if step.get("id") == "revision")["run"]


def test_template_exists() -> None:
    assert TEMPLATE.is_file()


def test_triggers() -> None:
    on = load(TEMPLATE)["on"]
    assert set(on) == {"pull_request", "push"}
    assert on["pull_request"] is None, "no branch filter: every PR runs the check"
    assert list(on["push"]) == ["branches"], "push runs on the default branch only"
    assert len(on["push"]["branches"]) == 1


def test_permissions_are_read_only() -> None:
    workflow = load(TEMPLATE)
    assert workflow["permissions"] == {"contents": "read"}
    assert "permissions" not in the_job(workflow), "the job does not widen the token"


def test_no_privileged_triggers_secrets_or_skips() -> None:
    text = TEMPLATE.read_text()
    for forbidden in ("pull_request_target", "workflow_run", "secrets.", "continue-on-error"):
        assert forbidden not in text, forbidden


def test_concurrency() -> None:
    assert load(TEMPLATE)["concurrency"] == {
        "group": "uv-lock-revision-${{ github.event.pull_request.number || github.ref }}",
        "cancel-in-progress": True,
    }


def test_job_is_the_required_check() -> None:
    job = the_job(load(TEMPLATE))
    # bin/github-required-checks in ol-infrastructure matches the job name exactly.
    assert job["name"] == "uv.lock revision"
    assert job["runs-on"] == "ubuntu-latest"
    assert 0 < job["timeout-minutes"] <= 60


def test_expected_revision_is_the_single_adapt_knob() -> None:
    job = the_job(load(TEMPLATE))
    assert list(job["env"]) == ["EXPECTED_REVISION"]
    assert str(job["env"]["EXPECTED_REVISION"]).isdigit()
    adapts = [line for line in TEMPLATE.read_text().splitlines() if "ADAPT" in line]
    assert any("EXPECTED_REVISION" in line for line in adapts), "the revision is marked ADAPT"


def test_needs_no_toolchain() -> None:
    """The check reads the file, so no step installs or runs uv -- it cannot relock anything.

    Asserted against `uses:` refs and invoked commands rather than the whole file, because
    the error message names `uv add` and `uv lock --upgrade` as the things that move the
    revision, and the glob matches `*uv.lock`.
    """
    workflow = load(TEMPLATE)
    actions = [step["uses"].split("@")[0] for step in the_job(workflow)["steps"] if "uses" in step]
    assert actions == ["actions/checkout"]
    for line in check_script().splitlines():
        assert not line.strip().startswith(("uv ", "uvx ", "pip ")), line


def test_every_action_is_pinned_by_sha_with_a_version_comment() -> None:
    uses = [match for line in TEMPLATE.read_text().splitlines() if (match := USES_LINE.match(line))]
    assert uses
    for match in uses:
        assert PINNED_REF.match(match["ref"]), match["ref"]
        assert VERSION_COMMENT.match(match["rest"]), f"{match['ref']} needs a `# vX.Y.Z` comment"


def test_pins_match_the_autofix_templates() -> None:
    """One commit per action across every template, so a bump cannot land half-applied."""

    def pins(path: Path) -> dict[str, str]:
        found = {}
        for line in path.read_text().splitlines():
            if match := USES_LINE.match(line):
                action, _, sha = match["ref"].partition("@")
                found[action] = sha
        return found

    mine = pins(TEMPLATE)
    for other in AUTOFIX_TEMPLATES:
        for action, sha in pins(other).items():
            if action in mine:
                assert mine[action] == sha, f"{action} differs from {other.name}"


def test_checkout_does_not_persist_credentials() -> None:
    checkout = the_job(load(TEMPLATE))["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False


def run_check(tmp_path: Path, lockfiles: dict[str, int | None], expected: str = "5"):
    """Run the template's own script over a throwaway repo, returning the CompletedProcess."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for name, revision in lockfiles.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "version = 1\n"
        if revision is not None:
            body += f"revision = {revision}\n"
        path.write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return subprocess.run(
        ["bash", "-c", check_script()],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "EXPECTED_REVISION": expected},
        check=False,
    )


@pytest.mark.parametrize(
    "lockfiles",
    [
        pytest.param({"uv.lock": 5}, id="single"),
        pytest.param({f"p{n}/uv.lock": 5 for n in range(12)}, id="workspace-of-twelve"),
    ],
)
def test_passes_when_every_lockfile_matches(tmp_path: Path, lockfiles: dict) -> None:
    assert run_check(tmp_path, lockfiles).returncode == 0


def test_fails_when_an_older_uv_lowered_the_revision(tmp_path: Path) -> None:
    result = run_check(tmp_path, {"uv.lock": 3})
    assert result.returncode == 1
    assert "::error file=uv.lock::" in result.stdout
    assert "revision is 3, expected 5" in result.stdout


def test_fails_on_the_one_drifted_lockfile_of_several(tmp_path: Path) -> None:
    result = run_check(tmp_path, {"a/uv.lock": 5, "b/uv.lock": 3, "c/uv.lock": 5})
    assert result.returncode == 1
    assert "::error file=b/uv.lock::" in result.stdout
    assert "a/uv.lock" not in result.stdout
    assert "c/uv.lock" not in result.stdout


def test_fails_when_the_revision_key_is_absent(tmp_path: Path) -> None:
    result = run_check(tmp_path, {"uv.lock": None})
    assert result.returncode == 1
    assert "revision is absent" in result.stdout


def test_fails_when_the_repository_has_no_lockfile(tmp_path: Path) -> None:
    """Adopting the template where it does not belong is a mistake worth surfacing."""
    result = run_check(tmp_path, {"README.md": None})
    assert result.returncode == 1
    assert "no uv.lock found" in result.stdout


def test_fails_when_expected_revision_was_left_unadapted(tmp_path: Path) -> None:
    result = run_check(tmp_path, {"uv.lock": 5}, expected="3")
    assert result.returncode == 1
