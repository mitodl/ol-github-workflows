"""Tests for the reference prek + autofix.ci workflow templates.

Two kinds of test, both against the files in workflow-templates/:

* Structural tests read each template and assert the properties the contract
  (docs/prek-autofix-contract.md §3.1 and §5) requires.
* Behavioral tests run each template's own `run:` scripts, taken from the YAML, against
  throwaway git repositories whose hooks are fixable, non-fixable, non-converging, and so
  on. The last step, autofix-ci/action, is emulated from its source at the pinned commit
  (c5b2d67, index.ts): `git add --all`, nothing staged means "Nothing to do" and success,
  any staged path containing ".github" is refused, anything else starts a fix and fails
  the step. What the autofix.ci server then does is not emulated; the pilots record it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = sorted((ROOT / "workflow-templates").glob("autofix-*.yml"))
TEMPLATE_IDS = [path.stem for path in TEMPLATES]
AUTOFIX_ACTION = "autofix-ci/action"
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+)(?P<rest>.*)$")
PINNED_REF = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s*#\s*v\d+(\.\d+)*$")
# Steps after the toolchain setup; identical in every template (test_shared_steps_match).
SHARED_STEP_IDS = ["clean-tree", "fixing-pass", "converge", "no-drift", "autofix"]
PREK = shutil.which("prek", path=str(ROOT / ".venv" / "bin")) or shutil.which("prek")


def load(path: Path) -> dict:
    """Parse a workflow, mapping YAML 1.1's boolean `on` key back to "on"."""
    workflow = yaml.safe_load(path.read_text())
    if True in workflow:
        workflow["on"] = workflow.pop(True)
    return workflow


def the_job(workflow: dict) -> dict:
    jobs = workflow["jobs"]
    assert list(jobs) == ["prek"], "each template defines exactly one job, `prek`"
    return jobs["prek"]


def steps_by_id(workflow: dict) -> dict[str, dict]:
    return {step["id"]: step for step in the_job(workflow)["steps"] if "id" in step}


@pytest.fixture(params=TEMPLATES, ids=TEMPLATE_IDS)
def template(request: pytest.FixtureRequest) -> Path:
    return request.param


# --- Structure ---------------------------------------------------------------------------


def test_templates_exist() -> None:
    assert TEMPLATE_IDS == ["autofix-node", "autofix-standalone", "autofix-uv"]


def test_workflow_name_is_autofix_ci(template: Path) -> None:
    # The action throws unless GITHUB_WORKFLOW is exactly "autofix.ci".
    assert load(template)["name"] == "autofix.ci"


def test_triggers(template: Path) -> None:
    on = load(template)["on"]
    assert set(on) == {"pull_request", "push"}
    assert on["pull_request"] is None, "no branch filter: every PR runs the check"
    assert list(on["push"]) == ["branches"], "push runs on the default branch only"
    assert len(on["push"]["branches"]) == 1


def test_permissions_are_read_only(template: Path) -> None:
    workflow = load(template)
    assert workflow["permissions"] == {"contents": "read"}
    assert "permissions" not in the_job(workflow), "no job widens the token"


def test_no_privileged_triggers_secrets_or_skips(template: Path) -> None:
    text = template.read_text()
    for forbidden in (
        "pull_request_target",
        "workflow_run",
        "secrets.",
        "SKIP",
        "continue-on-error",
    ):
        assert forbidden not in text, forbidden


def test_concurrency(template: Path) -> None:
    assert load(template)["concurrency"] == {
        "group": "autofix-${{ github.event.pull_request.number || github.ref }}",
        "cancel-in-progress": True,
    }


def test_job_is_the_required_check(template: Path) -> None:
    job = the_job(load(template))
    # bin/github-required-checks in ol-infrastructure matches the job name exactly.
    assert job["name"] == "prek"
    assert job["runs-on"] == "ubuntu-latest"
    assert 0 < job["timeout-minutes"] <= 60


def test_every_action_is_pinned_by_sha_with_a_version_comment(template: Path) -> None:
    uses = [USES_LINE.match(line) for line in template.read_text().splitlines()]
    uses = [match for match in uses if match]
    assert uses
    for match in uses:
        assert PINNED_REF.match(match["ref"]), match["ref"]
        assert VERSION_COMMENT.match(match["rest"]), f"{match['ref']} needs a `# vX.Y.Z` comment"


def test_all_templates_pin_the_same_commit_per_action() -> None:
    pins: dict[str, set[str]] = {}
    own = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
    for path in [*TEMPLATES, *own]:
        for line in path.read_text().splitlines():
            if match := USES_LINE.match(line):
                action, _, sha = match["ref"].partition("@")
                pins.setdefault(action, set()).add(sha)
    assert {action: shas for action, shas in pins.items() if len(shas) > 1} == {}


def test_checkout_does_not_persist_credentials(template: Path) -> None:
    checkout = the_job(load(template))["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False


def test_step_order(template: Path) -> None:
    steps = the_job(load(template))["steps"]
    ids = [step.get("id") for step in steps]
    tail = ids[-len(SHARED_STEP_IDS) :]
    assert tail == SHARED_STEP_IDS, "the guard comes right before the first pass; autofix is last"
    assert not any(ids[: -len(SHARED_STEP_IDS)]), "setup steps carry no ids"


def test_shared_steps_match() -> None:
    """Every template shares the same hook and fix steps, so the behavior tests cover all."""
    shared = [
        [steps_by_id(load(path))[step_id] for step_id in SHARED_STEP_IDS] for path in TEMPLATES
    ]
    assert all(steps == shared[0] for steps in shared)


def test_passes_and_fix_step(template: Path) -> None:
    steps = steps_by_id(load(template))
    assert steps["fixing-pass"]["run"].strip().endswith("|| true")
    converge = steps["converge"]["run"]
    assert "--show-diff-on-failure" in converge
    assert "||" not in converge
    assert "if" not in steps["converge"]
    assert steps["no-drift"]["if"] == "github.event_name != 'pull_request'"
    autofix = steps["autofix"]
    assert autofix["uses"].startswith(f"{AUTOFIX_ACTION}@")
    assert autofix["if"] == "github.event_name == 'pull_request'"
    assert autofix["with"] == {"fail-fast": False}


def test_prek_is_pinned_exactly(template: Path) -> None:
    text = template.read_text()
    if template.stem == "autofix-standalone":
        assert re.search(r'prek-version: "\d+\.\d+\.\d+"', text)
    elif template.stem == "autofix-uv":
        assert "uv sync --frozen --only-group prek" in text
        assert re.search(r'version: "\d+\.\d+\.\d+"', text), "setup-uv pins uv"
    else:
        assert "yarn install --immutable" in text
        assert re.search(r'node-version: "\d+\.\d+\.\d+"', text)


def test_this_repository_runs_the_uv_template() -> None:
    ours = ROOT / ".github" / "workflows" / "autofix.yml"
    assert ours.read_text() == (ROOT / "workflow-templates" / "autofix-uv.yml").read_text()


def test_prek_group_is_the_single_pin() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert re.search(r'^prek = \["prek==\d+\.\d+\.\d+"\]$', pyproject, re.MULTILINE)
    assert '{ include-group = "prek" }' in pyproject


# --- Behavior ----------------------------------------------------------------------------

FIXABLE = """\
  - id: strip-trailing-spaces
    name: strip trailing spaces
    entry: sed -i -e 's/[[:space:]]*$//'
    language: system
    files: \\.txt$
"""
NON_FIXABLE = """\
  - id: forbid-marker
    name: forbid the FORBIDDEN marker
    entry: FORBIDDEN
    language: pygrep
    files: \\.txt$
"""
NON_CONVERGING = """\
  - id: append-forever
    name: append a line every run
    entry: sh -c 'for f in "$@"; do echo more >> "$f"; done' --
    language: system
    files: \\.txt$
"""
FORMAT_WORKFLOWS = """\
  - id: strip-trailing-spaces-everywhere
    name: strip trailing spaces, workflows included
    entry: sed -i -e 's/[[:space:]]*$//'
    language: system
    files: \\.(txt|yml)$
"""


@dataclass
class Run:
    """The outcome of one simulated workflow run."""

    event: str
    failed_step: str | None = None
    fix_files: list[str] = field(default_factory=list)
    fix_started: bool = False
    logs: dict[str, str] = field(default_factory=dict)

    @property
    def green(self) -> bool:
        return self.failed_step is None


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def make_repo(tmp_path: Path, hooks: str, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".pre-commit-config.yaml").write_text(f"repos:\n- repo: local\n  hooks:\n{hooks}")
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "fixture")
    git(repo, "config", "user.email", "fixture@example.com")
    git(repo, "add", "--all")
    git(repo, "commit", "-q", "-m", "fixture")
    return repo


def simulate(template: Path, repo: Path, event: str, prek_home: Path) -> Run:
    """Run the template's steps from the guard onward, as Actions would for `event`."""
    steps = steps_by_id(load(template))
    env = {
        **os.environ,
        "PATH": f"{Path(PREK).parent}{os.pathsep}{os.environ['PATH']}",
        "PREK_HOME": str(prek_home),
        "GITHUB_EVENT_NAME": event,
        "GITHUB_REF_NAME": "main",
    }
    run = Run(event)
    for step_id in ["clean-tree", "fixing-pass", "converge", "no-drift"]:
        step = steps[step_id]
        condition = step.get("if")
        if condition == "github.event_name != 'pull_request'" and event == "pull_request":
            continue
        assert condition in (None, "github.event_name != 'pull_request'"), condition
        # Actions runs `run:` with `bash -e {0}` on Linux when no shell is given.
        result = subprocess.run(
            ["bash", "-e", "-c", step["run"]],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        run.logs[step_id] = result.stdout + result.stderr
        if result.returncode:
            run.failed_step = step_id
            return run
    if event == "pull_request":
        emulate_autofix_action(repo, run)
    return run


def emulate_autofix_action(repo: Path, run: Run) -> None:
    """The decision half of autofix-ci/action at c5b2d67 (index.ts)."""
    git(repo, "reset", "-q")
    git(repo, "-c", "core.fileMode=false", "add", "--all")
    staged = git(
        repo,
        "-c",
        "core.quotepath=false",
        "diff",
        "--name-only",
        "--staged",
        "--no-renames",
    )
    if not staged:
        return  # "Nothing to do!" and the step succeeds
    run.fix_files = staged.split()
    if any(".github" in path for path in run.fix_files):
        run.failed_step = "autofix"  # "not allowed to modify the .github directory"
        return
    run.fix_started = True
    run.failed_step = "autofix"  # setFailed("Autofix task started.") keeps this commit red


def bot_commit(repo: Path) -> None:
    """What autofix-ci[bot] pushes: the staged fix, as one commit."""
    git(repo, "commit", "-q", "-m", "[autofix.ci] apply automated fixes")


needs_prek = pytest.mark.skipif(PREK is None, reason="prek is not installed; run `uv sync`")


@pytest.fixture
def prek_home(tmp_path: Path) -> Path:
    return tmp_path / "prek-home"


@needs_prek
def test_clean_tree_passes(template: Path, tmp_path: Path, prek_home: Path) -> None:
    repo = make_repo(tmp_path, FIXABLE + NON_FIXABLE, {"a.txt": "clean\n"})
    for event in ("pull_request", "push"):
        run = simulate(template, repo, event, prek_home)
        assert run.green, run.logs
        assert not run.fix_started


@needs_prek
def test_fixable_change_is_committed_once(template: Path, tmp_path: Path, prek_home: Path) -> None:
    repo = make_repo(tmp_path, FIXABLE, {"a.txt": "trailing   \n", "b.txt": "clean\n"})
    first = simulate(template, repo, "pull_request", prek_home)
    assert first.failed_step == "autofix", first.logs
    assert first.fix_started
    assert first.fix_files == ["a.txt"]

    bot_commit(repo)
    second = simulate(template, repo, "pull_request", prek_home)
    assert second.green, second.logs
    assert not second.fix_started, "the run on the bot's commit makes no further commit"


@needs_prek
def test_fixable_drift_on_push_fails_without_a_fix(
    template: Path, tmp_path: Path, prek_home: Path
) -> None:
    repo = make_repo(tmp_path, FIXABLE, {"a.txt": "trailing   \n"})
    run = simulate(template, repo, "push", prek_home)
    assert run.failed_step == "no-drift", run.logs
    assert not run.fix_started
    assert "a.txt" in run.logs["no-drift"]


@needs_prek
def test_non_fixable_failure_stays_red(template: Path, tmp_path: Path, prek_home: Path) -> None:
    repo = make_repo(tmp_path, NON_FIXABLE, {"a.txt": "FORBIDDEN\n"})
    for event in ("pull_request", "push"):
        run = simulate(template, repo, event, prek_home)
        assert run.failed_step == "converge", run.logs
        assert not run.fix_started


@needs_prek
def test_fixable_and_non_fixable_together_push_no_fix(
    template: Path, tmp_path: Path, prek_home: Path
) -> None:
    repo = make_repo(
        tmp_path,
        FIXABLE + NON_FIXABLE,
        {"a.txt": "trailing   \n", "b.txt": "FORBIDDEN\n"},
    )
    run = simulate(template, repo, "pull_request", prek_home)
    assert run.failed_step == "converge", run.logs
    assert not run.fix_started, "a partial fix is not pushed while a hook still fails"


@needs_prek
def test_non_converging_hooks_fail(template: Path, tmp_path: Path, prek_home: Path) -> None:
    repo = make_repo(tmp_path, NON_CONVERGING, {"a.txt": "x\n"})
    run = simulate(template, repo, "pull_request", prek_home)
    assert run.failed_step == "converge", run.logs
    assert not run.fix_started


@needs_prek
def test_setup_leftovers_are_never_committed(
    template: Path, tmp_path: Path, prek_home: Path
) -> None:
    repo = make_repo(tmp_path, FIXABLE, {"a.txt": "clean\n"})
    (repo / "left-by-setup.log").write_text("an untracked file a setup step wrote\n")
    run = simulate(template, repo, "pull_request", prek_home)
    assert run.failed_step == "clean-tree", run.logs
    assert "left-by-setup.log" in run.logs["clean-tree"]
    assert not run.fix_started


@needs_prek
def test_fix_under_github_is_refused(template: Path, tmp_path: Path, prek_home: Path) -> None:
    workflow = "on: push   \njobs: {}\n"
    repo = make_repo(tmp_path, FORMAT_WORKFLOWS, {".github/workflows/ci.yml": workflow})
    run = simulate(template, repo, "pull_request", prek_home)
    assert run.failed_step == "autofix", run.logs
    assert not run.fix_started
    assert run.fix_files == [".github/workflows/ci.yml"]
