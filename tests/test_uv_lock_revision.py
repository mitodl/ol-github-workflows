"""Tests for the uv.lock revision action and the workflow template that calls it.

Structural tests assert the properties the contract (docs/uv-lock-revision-contract.md)
requires, mirroring tests/test_templates.py for the autofix family. Behavioral tests run
the action's own `run:` script, taken from the YAML, against throwaway git repositories
whose lockfiles are correct, drifted, absent, and so on -- so the assertions cover the
script that actually ships rather than a copy of it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from workflow_contract import (
    ROOT,
    assert_checkout_does_not_persist_credentials,
    assert_every_action_is_pinned,
    assert_read_only_permissions,
    assert_text_forbids,
    assert_triggers,
    load,
)

ACTION = ROOT / "actions" / "uv-lock-revision" / "action.yml"
TEMPLATE = ROOT / "workflow-templates" / "uv-lock-revision.yml"
ADOPTED = ROOT / ".github" / "workflows" / "uv-lock-revision.yml"
JOB_ID = "uv-lock-revision"
ACTION_REF = "mitodl/ol-github-workflows/actions/uv-lock-revision"


def the_job(workflow: dict) -> dict:
    jobs = workflow["jobs"]
    assert list(jobs) == [JOB_ID], f"the workflow defines exactly one job, `{JOB_ID}`"
    return jobs[JOB_ID]


def action_steps() -> list[dict]:
    runs = load(ACTION)["runs"]
    assert runs["using"] == "composite"
    return runs["steps"]


CHECK = ROOT / "actions" / "uv-lock-revision" / "check.py"


def check_script() -> str:
    """The script the action runs, read from the file the action ships."""
    return CHECK.read_text()


def run_script(tmp_path: Path, env: dict[str, str]):
    """Run check.py against a repository, as the action's step does."""
    return subprocess.run(
        [sys.executable, str(CHECK)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        check=False,
    )


# --- The action --------------------------------------------------------------------------


def test_action_exists() -> None:
    assert ACTION.is_file()


def test_action_takes_the_expected_revision_as_a_required_input() -> None:
    inputs = load(ACTION)["inputs"]
    assert list(inputs) == ["expected-revision", "expected-version"]
    assert inputs["expected-revision"]["required"] is True


def test_expected_version_is_optional_and_defaults_to_the_only_version_uv_writes() -> None:
    """Optional, so an adopter pinned at the previous tag takes the bump unattended.

    Making it required would turn a Renovate pin bump into a broken workflow in every
    repository that has adopted the action.
    """
    version = load(ACTION)["inputs"]["expected-version"]
    assert version.get("required") is not True
    assert version["default"] == "1"


def test_the_input_reaches_the_script_through_the_environment() -> None:
    """An expression expanded into the script body would be shell, not a value."""
    script_step = next(step for step in action_steps() if step.get("id") == "revision")
    assert script_step["env"] == {
        "EXPECTED_REVISION": "${{ inputs.expected-revision }}",
        "EXPECTED_VERSION": "${{ inputs.expected-version }}",
    }
    assert script_step["shell"] == "bash"
    assert "${{" not in script_step["run"]


def test_action_checks_out_without_persisting_credentials() -> None:
    assert_checkout_does_not_persist_credentials(load(ACTION)["runs"])


def test_the_checkout_fetches_the_commit_the_ratchet_compares_against() -> None:
    """Two commits: the merge commit, and the branch being merged into as its first parent.

    Without this the ratchet has no before, silently degrades to the floor alone, and a
    rollback merges green.
    """
    checkout = load(ACTION)["runs"]["steps"][0]
    assert checkout["with"]["fetch-depth"] == 2


def test_action_is_pinned_by_sha_with_a_version_comment() -> None:
    # That the pins agree with the templates is covered by
    # test_templates.py::test_all_templates_pin_the_same_commit_per_action, which spans
    # every template and every action rather than only the autofix family.
    assert_every_action_is_pinned(ACTION)


def test_action_needs_no_toolchain() -> None:
    """The check reads the file, so no step installs or runs uv -- it cannot relock anything.

    Asserted against `uses:` refs and invoked commands rather than the whole file, because
    the error message names `uv add` and `uv lock --upgrade` as the things that move the
    revision, and the glob matches `*uv.lock`.
    """
    actions = [step["uses"].split("@")[0] for step in action_steps() if "uses" in step]
    assert actions == ["actions/checkout"]
    for line in check_script().splitlines():
        assert not line.strip().startswith(("uv ", "uvx ", "pip ")), line
    assert "import tomllib" in check_script(), "the parser is stdlib, so nothing is installed"


def test_action_grants_itself_nothing() -> None:
    assert_text_forbids(ACTION, "secrets.", "github-token", "continue-on-error")


# --- The caller template -----------------------------------------------------------------


def test_template_exists() -> None:
    assert TEMPLATE.is_file()


def test_triggers() -> None:
    assert_triggers(load(TEMPLATE)["on"])


@pytest.mark.parametrize("path", [TEMPLATE, ADOPTED], ids=["template", "adopted"])
def test_permissions_are_read_only(path: Path) -> None:
    workflow = load(path)
    assert_read_only_permissions(workflow, the_job(workflow))


@pytest.mark.parametrize("path", [TEMPLATE, ADOPTED], ids=["template", "adopted"])
def test_no_privileged_triggers_secrets_or_skips(path: Path) -> None:
    """Asserted against the adopted copy too.

    test_this_repository_runs_the_template compares a fixed list of keys, so a widened
    token or a `continue-on-error` added only to the copy this repository actually runs
    would otherwise pass both it and every other test here.
    """
    assert_text_forbids(
        path, "pull_request_target", "workflow_run", "secrets.", "continue-on-error"
    )


def test_concurrency() -> None:
    assert load(TEMPLATE)["concurrency"] == {
        "group": "uv-lock-revision-${{ github.event.pull_request.number || github.ref }}",
        "cancel-in-progress": True,
    }


def test_job_is_the_required_check() -> None:
    """A composite action keeps this name as the whole context.

    A reusable workflow would make it `<caller job> / <called job>`, renaming the required
    check in every repository that has adopted the template. bin/github-required-checks in
    ol-infrastructure matches the job name exactly.
    """
    job = the_job(load(TEMPLATE))
    assert job["name"] == "uv.lock revision"
    assert job["runs-on"] == "ubuntu-latest"
    assert 0 < job["timeout-minutes"] <= 60


def test_the_template_is_nothing_but_the_action() -> None:
    """No step of its own: whatever the check does, it does centrally or not at all."""
    steps = the_job(load(TEMPLATE))["steps"]
    assert len(steps) == 1
    assert steps[0]["uses"].startswith(f"{ACTION_REF}@")
    assert list(steps[0]["with"]) == ["expected-revision"]


def test_the_template_pins_the_action_by_sha() -> None:
    """`@main` would let this repository change CI behavior everywhere with no review there."""
    assert_every_action_is_pinned(TEMPLATE)


def test_the_adapt_lines_are_exactly_the_two_the_contract_lists() -> None:
    """Asserted as a set, not a membership test.

    The action ref deliberately carries no ADAPT marker -- a repository that repoints it
    somewhere else is no longer running the shared check -- and a membership test would not
    notice one being added.
    """
    with_ = the_job(load(TEMPLATE))["steps"][0]["with"]
    assert str(with_["expected-revision"]).isdigit()
    adapts = [
        line.split("# ADAPT:")[0].strip()
        for line in TEMPLATE.read_text().splitlines()
        if "# ADAPT:" in line
    ]
    assert len(adapts) == 2, adapts
    assert any(line.startswith("branches:") for line in adapts), adapts
    assert any(line.startswith("expected-revision:") for line in adapts), adapts


# --- This repository's own adoption ------------------------------------------------------


def test_this_repository_runs_the_template() -> None:
    """The adopted copy may differ at the action ref and the revision, and nowhere else.

    test_templates.py asserts byte-equality for the autofix family. This one cannot: the
    adopted copy calls the action by self-repository ref, so a pull request here exercises
    the action as the branch defines it rather than whatever is already on main. Everything
    else, including the permissions and the single step, has to match or adopting proves
    nothing.
    """

    template, adopted = load(TEMPLATE), load(ADOPTED)
    for key in ("name", "on", "permissions", "concurrency"):
        assert adopted[key] == template[key], key

    adopted_job, template_job = the_job(adopted), the_job(template)
    for key in ("name", "runs-on", "timeout-minutes"):
        assert adopted_job[key] == template_job[key], key

    (step,) = adopted_job["steps"]
    assert step["uses"] == "$/actions/uv-lock-revision"
    assert list(step["with"]) == list(template_job["steps"][0]["with"])


def test_the_adopted_copy_expects_this_repositorys_revision() -> None:
    """A floor, so this asserts `<=` rather than equality.

    Equality would turn red the moment a Renovate bump here relocks to a higher revision
    -- reinstating, in this job, exactly the blockage the floor exists to remove.
    """
    expected = the_job(load(ADOPTED))["steps"][0]["with"]["expected-revision"]
    locks = (ROOT / "uv.lock").read_text()
    actual = re.search(r"^revision = (\d+)", locks, re.M)
    assert actual, "uv.lock has no revision key"
    assert int(expected) <= int(actual.group(1)), "this repository is below its own floor"


# --- Behavior ----------------------------------------------------------------------------


def run_check(
    tmp_path: Path,
    lockfiles: dict[str, int | None],
    expected: str = "5",
    expected_version: str = "1",
    version: int = 1,
):
    """Run the action's own script over a throwaway repo, returning the CompletedProcess.

    Stages the lockfiles without committing, so `HEAD^1` does not resolve and the ratchet
    sits out -- these are the floor's cases. run_ratchet covers the rest.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for name, revision in lockfiles.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = f"version = {version}\n"
        if revision is not None:
            body += f"revision = {revision}\n"
        path.write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return run_script(
        tmp_path, {"EXPECTED_REVISION": expected, "EXPECTED_VERSION": expected_version}
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


def test_fails_when_a_lockfile_is_below_the_floor(tmp_path: Path) -> None:
    result = run_check(tmp_path, {"uv.lock": 3})
    assert result.returncode == 1
    assert "::error file=uv.lock::" in result.stdout
    assert "revision is 3, below the floor of 5" in result.stdout


def assert_blames_only(result, offender: str, *innocent: str) -> None:
    """One offender annotated, the rest not mentioned at all.

    Shared by the floor and ratchet cases so the two cannot drift on what "only this
    file" means; each still sets up its own scenario.
    """
    assert result.returncode == 1
    assert f"::error file={offender}::" in result.stdout
    for other in innocent:
        assert other not in result.stdout, other


def test_fails_on_the_one_drifted_lockfile_of_several(tmp_path: Path) -> None:
    result = run_check(tmp_path, {"a/uv.lock": 5, "b/uv.lock": 3, "c/uv.lock": 5})
    assert_blames_only(result, "b/uv.lock", "a/uv.lock", "c/uv.lock")


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
    return run_script(tmp_path, {"EXPECTED_REVISION": expected, "EXPECTED_VERSION": "1"})


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
    assert "revision is 3, below the floor of 5" in result.stdout


def test_annotates_a_lockfile_tracked_but_missing_from_the_checkout(tmp_path: Path) -> None:
    """Without the guard this aborted the whole run on awk's exit 2, annotating nothing."""
    result = run_raw(tmp_path, b"version = 1\nrevision = 5\n", unlink=True)
    assert result.returncode == 1
    assert "::error file=uv.lock::tracked by git but missing" in result.stdout
    assert "checked 1 lockfile(s)" in result.stdout, "the summary line still runs"


def test_a_lockfile_above_the_floor_passes_with_a_notice(tmp_path: Path) -> None:
    """A revision rising is a newer uv writing a format an older one still reads.

    Failing it would block every Renovate bump in a repository whose floor has not caught
    up, which is what the exact comparison this replaced actually did.
    """
    result = run_check(tmp_path, {"uv.lock": 5}, expected="3")
    assert result.returncode == 0
    assert "::notice file=uv.lock::" in result.stdout
    assert "revision is 5, above the floor of 3" in result.stdout
    assert "::error" not in result.stdout


@pytest.mark.parametrize(
    "expected",
    [
        pytest.param("", id="omitted"),
        pytest.param("  ", id="blank"),
        pytest.param("v5", id="version-prefixed"),
        pytest.param("5.0", id="dotted"),
        pytest.param("5; rm -rf /", id="injected"),
    ],
)
def test_rejects_an_expected_revision_that_is_not_a_number(tmp_path: Path, expected: str) -> None:
    """An omitted `with:` reaches the script empty -- GitHub does not enforce `required:`.

    Empty is the dangerous one: it equals the empty `actual` of a lockfile with no revision
    key, so without this guard the check passes exactly the drift it exists to catch.
    """
    result = run_check(tmp_path, {"uv.lock": None}, expected=expected)
    assert result.returncode == 1
    assert "not a revision number" in result.stdout
    assert "checked" not in result.stdout, "it fails before scanning anything"


# --- The ratchet -------------------------------------------------------------------------

COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def run_ratchet(
    tmp_path: Path,
    base: dict[str, int | None],
    head: dict[str, int | None],
    expected: str = "3",
):
    """Two commits, so the script has a `HEAD^1` to compare against.

    On a pull request the checked-out commit is the merge commit and its first parent is
    the branch being merged into, which is what this stands in for. A lockfile absent from
    `base` is one the head commit adds, and has nothing to have fallen from.
    """
    env = {**os.environ, **COMMIT_ENV}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    for state in (base, head):
        for name, revision in state.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            body = "version = 1\n"
            if revision is not None:
                body += f"revision = {revision}\n"
            path.write_text(body)
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, env=env)
        subprocess.run(
            ["git", "commit", "-q", "-m", "state", "--allow-empty"],
            cwd=tmp_path,
            check=True,
            env=env,
        )
    return run_script(tmp_path, {"EXPECTED_REVISION": expected, "EXPECTED_VERSION": "1"})


def test_fails_when_an_older_uv_lowered_the_revision(tmp_path: Path) -> None:
    """The one direction that loses data, and the reason the check exists.

    The floor cannot catch this: the repository's floor is 3, and 3 clears it. Only the
    comparison against what the branch already has shows that something was given up.
    """
    result = run_ratchet(tmp_path, {"uv.lock": 5}, {"uv.lock": 3})
    assert result.returncode == 1
    assert "::error file=uv.lock::" in result.stdout
    assert "revision fell from 5 to 3" in result.stdout


@pytest.mark.parametrize(
    ("base", "head", "id_"),
    [
        pytest.param(3, 5, "renovate-bumps-the-format", id="forward"),
        pytest.param(5, 5, "nothing-moved", id="steady"),
        pytest.param(3, 3, "nothing-moved-at-the-floor", id="at-floor"),
    ],
)
def test_the_ratchet_permits_everything_but_a_fall(
    tmp_path: Path, base: int, head: int, id_: str
) -> None:
    result = run_ratchet(tmp_path, {"uv.lock": base}, {"uv.lock": head})
    assert result.returncode == 0, result.stdout
    assert "::error" not in result.stdout


def test_names_only_the_lockfile_that_fell(tmp_path: Path) -> None:
    """A workspace where one lockfile regressed and the others did not."""
    result = run_ratchet(
        tmp_path,
        {"a/uv.lock": 5, "b/uv.lock": 5, "c/uv.lock": 5},
        {"a/uv.lock": 5, "b/uv.lock": 3, "c/uv.lock": 5},
    )
    assert_blames_only(result, "b/uv.lock", "::error file=a/uv.lock::", "::error file=c/uv.lock::")


def test_a_lockfile_the_head_commit_adds_has_nothing_to_have_fallen_from(
    tmp_path: Path,
) -> None:
    result = run_ratchet(tmp_path, {"a/uv.lock": 5}, {"a/uv.lock": 5, "b/uv.lock": 3})
    assert result.returncode == 0, result.stdout
    assert "::error" not in result.stdout


def test_says_so_when_there_is_no_parent_commit_to_compare_against(tmp_path: Path) -> None:
    """A run where the ratchet had no before must not read like one where it passed."""
    result = run_check(tmp_path, {"uv.lock": 5})
    assert result.returncode == 0
    assert "no parent commit in this checkout, so the ratchet did not run" in result.stdout


# --- The lockfile version ----------------------------------------------------------------


def test_fails_when_the_lockfile_version_moved(tmp_path: Path) -> None:
    """`version` is uv's backwards-incompatible tier, so it is exact where revision is not."""
    result = run_check(tmp_path, {"uv.lock": 5}, version=2)
    assert result.returncode == 1
    assert "lockfile version is 2, expected 1" in result.stdout


def test_passes_a_moved_version_the_repository_has_migrated_to(tmp_path: Path) -> None:
    result = run_check(tmp_path, {"uv.lock": 5}, expected_version="2", version=2)
    assert result.returncode == 0, result.stdout
    assert "::error" not in result.stdout


def test_rejects_an_expected_version_that_is_not_a_number(tmp_path: Path) -> None:
    result = run_check(tmp_path, {"uv.lock": 5}, expected_version="")
    assert result.returncode == 1
    assert "not a lockfile version number" in result.stdout
    assert "checked" not in result.stdout, "it fails before scanning anything"


def test_the_script_reaches_no_network() -> None:
    """The ratchet needs a commit it does not have by default; fetching it is the wrong fix.

    `persist-credentials: false` leaves no helper configured, so a fetch would fail in
    every private repository anyway. Asserted as a test rather than left to the comment
    on `fetch-depth`, because the temptation is real and silent.
    """
    script = check_script()
    # Word-bounded: a bare substring test matches `gh` inside "enough" and fails on prose.
    for reaching in (
        r"git\s+fetch",
        r"git\s+clone",
        r"git\s+pull",
        r"git\s+ls-remote",
        r"\bcurl\b",
        r"\bwget\b",
        r"\bgh\s",
    ):
        assert not re.search(reaching, script), reaching


def test_reads_the_base_copy_of_a_very_large_lockfile(tmp_path: Path) -> None:
    """The real lockfiles are hundreds of kilobytes; the fixtures above are two lines.

    Reading the base copy is where size has bitten before, so the biggest repositories
    get a case of their own rather than being covered only by the small ones.
    """
    env = {**os.environ, **COMMIT_ENV}
    filler = "".join(f"# filler {n}\n" for n in range(200_000))
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    for revision in (3, 5):
        (tmp_path / "uv.lock").write_text(f"version = 1\nrevision = {revision}\n{filler}")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, env=env)
        subprocess.run(
            ["git", "commit", "-q", "-m", "state", "--allow-empty"],
            cwd=tmp_path,
            check=True,
            env=env,
        )
    assert (tmp_path / "uv.lock").stat().st_size > 1_000_000, "the fixture must outgrow a pipe"
    result = run_script(tmp_path, {"EXPECTED_REVISION": "3", "EXPECTED_VERSION": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "also against" in result.stdout, "the ratchet ran rather than dying on the way"


# --- Reading the lockfile structurally ---------------------------------------------------


def write_lock(tmp_path: Path, body: str, name: str = "uv.lock") -> None:
    (tmp_path / name).write_text(body)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)


@pytest.mark.parametrize(
    ("literal", "value"),
    [
        pytest.param("1_0", 10, id="digit-separators"),
        pytest.param("0x10", 16, id="hexadecimal"),
        pytest.param("0b11", 3, id="binary"),
    ],
)
def test_a_version_is_read_as_toml_means_it_not_as_its_leading_digits(
    tmp_path: Path, literal: str, value: int
) -> None:
    """TOML's integer forms, which a scan for leading digits reads as 1, 0 and 0.

    uv writes canonical decimals, so this is not a lockfile anyone has. It is the class of
    question a parser answers and a scanner has to be told about one form at a time.
    """
    write_lock(tmp_path, f"version = {literal}\nrevision = 5\n")
    result = run_script(tmp_path, {"EXPECTED_REVISION": "3", "EXPECTED_VERSION": "1"})
    assert result.returncode == 1
    assert f"lockfile version is {value}, expected 1" in result.stdout


def test_a_package_version_cannot_stand_in_for_the_root_one(tmp_path: Path) -> None:
    """`version` under a `[[package]]` is that package's, and says nothing about the format."""
    write_lock(tmp_path, 'revision = 5\n\n[[package]]\nname = "x"\nversion = "1"\n')
    result = run_script(tmp_path, {"EXPECTED_REVISION": "3", "EXPECTED_VERSION": "1"})
    assert result.returncode == 1
    assert "root `version` is None" in result.stdout


def test_rejects_a_version_that_is_not_an_integer(tmp_path: Path) -> None:
    write_lock(tmp_path, 'version = "1"\nrevision = 5\n')
    result = run_script(tmp_path, {"EXPECTED_REVISION": "3", "EXPECTED_VERSION": "1"})
    assert result.returncode == 1
    assert "not a lockfile version" in result.stdout


def test_annotates_a_lockfile_that_is_not_readable_as_toml(tmp_path: Path) -> None:
    """A parse failure is this lockfile's problem, not a crash of the whole check."""
    write_lock(tmp_path, "version = 1\nrevision = [unclosed\n")
    result = run_script(tmp_path, {"EXPECTED_REVISION": "3", "EXPECTED_VERSION": "1"})
    assert result.returncode == 1
    assert "::error file=uv.lock::" in result.stdout
    assert "not readable as TOML" in result.stdout
    assert "Traceback" not in result.stderr


def test_the_summary_distinguishes_a_partial_ratchet_from_a_whole_one(tmp_path: Path) -> None:
    """A lockfile the change adds has no base copy, and the summary has to own up to it."""
    result = run_ratchet(tmp_path, {"a/uv.lock": 5}, {"a/uv.lock": 5, "b/uv.lock": 5})
    assert result.returncode == 0, result.stdout
    assert "1 of them also against" in result.stdout
    assert "the other 1 against the floor alone" in result.stdout
