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
from workflow_contract import (
    ROOT,
    assert_checkout_does_not_persist_credentials,
    assert_every_action_is_pinned,
    assert_read_only_permissions,
    assert_triggers,
    load,
)

TEMPLATE = ROOT / "workflow-templates" / "uv-lock-revision.yml"
JOB_ID = "uv-lock-revision"


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
    assert_triggers(load(TEMPLATE)["on"])


def test_permissions_are_read_only() -> None:
    workflow = load(TEMPLATE)
    assert_read_only_permissions(workflow, the_job(workflow))


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


def test_the_adapt_lines_are_exactly_the_two_the_contract_lists() -> None:
    """Asserted as a set, not a membership test.

    `persist-credentials` deliberately carries no ADAPT marker -- unlike the autofix
    templates, nothing here runs a networked `git` command -- and a membership test would
    not notice one being added back.
    """
    job = the_job(load(TEMPLATE))
    assert list(job["env"]) == ["EXPECTED_REVISION"]
    assert str(job["env"]["EXPECTED_REVISION"]).isdigit()
    adapts = [
        line.split("# ADAPT:")[0].strip()
        for line in TEMPLATE.read_text().splitlines()
        if "# ADAPT:" in line
    ]
    assert len(adapts) == 2, adapts
    assert any(line.startswith("branches:") for line in adapts), adapts
    assert any(line.startswith("EXPECTED_REVISION:") for line in adapts), adapts


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
    # That the pins agree with the other templates is covered by
    # test_templates.py::test_all_templates_pin_the_same_commit_per_action, which spans
    # every template rather than only the autofix family.
    assert_every_action_is_pinned(TEMPLATE)


def test_checkout_does_not_persist_credentials() -> None:
    assert_checkout_does_not_persist_credentials(the_job(load(TEMPLATE)))


ADOPTED = ROOT / ".github" / "workflows" / "uv-lock-revision.yml"
REVISION_LINE = re.compile(r'^(\s*EXPECTED_REVISION:\s*)"?\d+"?', re.M)


def test_this_repository_runs_the_template_verbatim() -> None:
    """The adopted copy may differ from the template at EXPECTED_REVISION and nowhere else.

    test_templates.py asserts byte-equality for the autofix family. This one cannot, because
    the adopted copy carries this repository's own revision -- but everything else, including
    the permissions and the exit status, has to match or adopting proves nothing.
    """

    def normalized(path: Path) -> str:
        return REVISION_LINE.sub(r"\1<REVISION>", path.read_text())

    assert normalized(ADOPTED) == normalized(TEMPLATE)


def test_the_adopted_copy_expects_this_repositorys_revision() -> None:
    expected = the_job(load(ADOPTED))["env"]["EXPECTED_REVISION"]
    locks = (ROOT / "uv.lock").read_text()
    actual = re.search(r"^revision = (\d+)", locks, re.M)
    assert actual, "uv.lock has no revision key"
    assert str(expected) == actual.group(1)


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


def run_raw(tmp_path: Path, body: bytes, expected: str = "5", unlink: bool = False):
    """As run_check, but writing the lockfile byte-for-byte: line endings and spacing matter."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    lock = tmp_path / "uv.lock"
    lock.write_bytes(body)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    if unlink:
        lock.unlink()
    return subprocess.run(
        ["bash", "-c", check_script()],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "EXPECTED_REVISION": expected},
        check=False,
    )


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"version = 1\nrevision = 5\n", id="plain"),
        pytest.param(b"version = 1\r\nrevision = 5\r\n", id="crlf"),
        pytest.param(b"version = 1\nrevision = 5   \n", id="trailing-spaces"),
        pytest.param(b"version = 1\nrevision=5\n", id="no-spaces"),
        pytest.param(b"version = 1\nrevision  =  5\n", id="wide-spacing"),
    ],
)
def test_reads_the_revision_whatever_the_spacing(tmp_path: Path, body: bytes) -> None:
    """A mismatch the eye cannot see -- "revision is 5, expected 5" -- is worse than no check."""
    assert run_raw(tmp_path, body).returncode == 0


def test_crlf_does_not_mask_a_real_drift(tmp_path: Path) -> None:
    result = run_raw(tmp_path, b"version = 1\r\nrevision = 3\r\n")
    assert result.returncode == 1
    assert "revision is 3, expected 5" in result.stdout


def test_annotates_a_lockfile_tracked_but_missing_from_the_checkout(tmp_path: Path) -> None:
    """Without the guard this aborted the whole run on awk's exit 2, annotating nothing."""
    result = run_raw(tmp_path, b"version = 1\nrevision = 5\n", unlink=True)
    assert result.returncode == 1
    assert "::error file=uv.lock::tracked by git but missing" in result.stdout
    assert "checked 1 lockfile(s)" in result.stdout, "the summary line still runs"


def test_fails_when_expected_revision_was_left_unadapted(tmp_path: Path) -> None:
    result = run_check(tmp_path, {"uv.lock": 5}, expected="3")
    assert result.returncode == 1
    assert "::error file=uv.lock::" in result.stdout
    assert "revision is 5, expected 3" in result.stdout
