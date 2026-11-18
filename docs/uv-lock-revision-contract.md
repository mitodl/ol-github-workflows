# uv.lock revision check contract

What `actions/uv-lock-revision` and the `workflow-templates/uv-lock-revision.yml` that calls
it guarantee, and what a repository adopting them has to do. Normative.
`tests/test_uv_lock_revision.py` asserts every structural claim except the pin consistency in
§3.6, which `tests/test_templates.py` asserts across every template and action at once.

## 1. The problem

uv writes a `revision` key into `uv.lock` identifying the lockfile format:

```toml
version = 1
revision = 5
```

Any uv command that **re-resolves** rewrites that key to whatever the running uv natively
writes. Measured:

| Operation | Rewrites `revision`? |
| --- | --- |
| `uv lock` with no resolution change | no, preserves it in both directions |
| `uv lock --upgrade`, `uv add` | yes |
| `uv sync --frozen`, `uv run --frozen`, `uv build` | no, never writes |

It moves in both directions. A newer uv raises it; an older uv lowers it and drops the
fields the newer format carries. A Renovate dependency bump re-resolves, which is how
[mitodl/mit-learn#4070](https://github.com/mitodl/mit-learn/pull/4070) changed one line of
`pyproject.toml`, zero package entries, and moved the lockfile from revision 3 to 5 with
nothing in the title or diff summary to say so.

Nothing else catches it. uv accepts a lockfile written by a different version, so both of
these pass against a lockfile whose format just changed underneath you:

```console
$ uv lock --check
$ uv sync --locked
```

## 2. Why not a uv version range

`[tool.uv].required-version` is the obvious lever and it does not work for this. uv has
only ever changed the revision **mid-minor**:

| Transition | Revision | Boundary |
| --- | --- | --- |
| `0.6.10` → `0.6.17` | 1 → 2 | mid-minor |
| `0.8.0` → `0.8.4` | 2 → 3 | mid-minor |
| `0.12.21` → `0.12.22` | 3 → 5 | mid-minor |

Every minor boundary - 0.7.0, 0.9.0, 0.10.0, 0.11.0, 0.12.0, 0.13.0 - carried the prior
revision forward unchanged. So a `>=X,<next-minor` bound permits exactly the kind of
change it is meant to prevent, while a bound tight enough to actually stop one has to be
an exact pin.

A range also fails everywhere uv runs, not just where a lockfile is written: it breaks
image builds and release jobs that only ever read the lockfile, and it breaks them after
merge rather than on the pull request.

Asserting the revision tests the property directly, in the one place a human is already
looking.

## 3. Required properties

### 3.1 Why a composite action and not a reusable workflow

The check is a composite action, so the adopting workflow calls it as a **step** inside its
own job. A reusable workflow called with `uses:` at job level would make the check context
`<caller job> / <called job>`, renaming the required check in every repository that has
adopted it, and GitHub offers no way to collapse that to one name. The action keeps the
context at `uv.lock revision` (§3.4) and keeps the `actions/checkout` pin in one place
instead of in every adopting repository.

### 3.2 The workflow

1. Triggers on every `pull_request` with no branch filter, and on `push` to the default
   branch only.
2. `permissions: {contents: read}` at workflow level; no job widens the token.
3. No `pull_request_target`, no `workflow_run`, no `secrets.`, no `continue-on-error`.
4. Exactly one job, `uv-lock-revision`, named `uv.lock revision`. The name is the required
   check context and `bin/github-required-checks` in ol-infrastructure matches it exactly,
   so it stays stable.
5. The job has exactly one step: the action. Whatever the check does, it does centrally or
   not at all.
6. The action is pinned to a 40-character SHA with a `# vX.Y.Z` comment, like any other
   action, and at the same commit per action as the `autofix-*.yml` templates. `@main` is
   out of contract: it would let this repository change CI behavior in every adopting
   repository with no review in any of them.

### 3.3 The action

7. The only action it uses is `actions/checkout`, and no step invokes `uv`. The check reads
   the file; it must not be able to relock anything.
8. `actions/checkout` sets `persist-credentials: false`, in every repository -- no step
   runs a `git` command that reaches the network.
9. `expected-revision` is the single required input, and it reaches the script through
   `env:` rather than `${{ }}` interpolation inside the body. An expression expanded into
   the script would be shell, and a caller's typo could run as one.
10. Every tracked path ending in `uv.lock` is checked, found with
    `git ls-files -z '*uv.lock'`, so a workspace with many lockfiles needs no extra
    configuration. The pathspec crosses `/` and matches a non-empty prefix, so a stray
    `notuv.lock` would be checked too -- it errs toward checking more, not less.
11. A repository with no `uv.lock` fails the check rather than passing vacuously.

## 4. Adoption

Copy `workflow-templates/uv-lock-revision.yml` to `.github/workflows/uv-lock-revision.yml`
and change only the `ADAPT` lines:

| Line | Change |
| --- | --- |
| `branches: [main]` | the repository's default branch |
| `expected-revision` | the `revision` every `uv.lock` in the repository is on |

The action ref carries no `ADAPT` marker. A repository that repoints it is no longer running
the shared check; Renovate keeps the pin current, as it does for every other action.

Read the current revision rather than assuming it:

```console
$ git ls-files -z '*uv.lock' | xargs -0 grep -h '^revision = ' | sort -u
revision = 5
```

More than one value means the lockfiles already disagree; reconcile them before adopting.

Add the job to the repository's required checks once it has passed on the default branch.

This repository's own `.github/workflows/uv-lock-revision.yml` is the one copy that differs:
it calls the action by self-repository ref, `uses: $/actions/uv-lock-revision`, so a pull
request here exercises the action as the branch defines it rather than whatever is already on
`main`. `tests/test_uv_lock_revision.py::test_this_repository_runs_the_template` asserts that
its triggers, permissions, concurrency, job name and inputs match the template's, and §3.2's
items 2 and 3 are asserted against it directly rather than through that comparison -- a
widened token or a `continue-on-error` reachable only in the copy this repository runs is the
one divergence a key-by-key comparison would not see. actionlint does not yet know the `$/`
syntax, so `.github/actionlint.yaml` filters the one message it produces for the one file.

## 5. Changing the format deliberately

Raise `expected-revision` in the same pull request as the relocked `uv.lock`. The diff then
shows both, which is the reviewable moment the check exists to create. Nothing automated
updates it - a bot cannot decide that a format change is intended.

## 6. What it does not do

It does not pin uv, and does not stop anyone running an old one. It reports that the
format moved, not who moved it. Repositories wanting a floor for unrelated reasons, such
as a `[tool.uv]` feature, keep setting `required-version` themselves; this check is
indifferent to it.
