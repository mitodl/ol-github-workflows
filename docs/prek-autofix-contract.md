# prek + autofix.ci migration contract

**Issue:** [mitodl/ol-infrastructure#5805](https://github.com/mitodl/ol-infrastructure/issues/5805)
**Inventory:** [`docs/plans/prek-autofix-migration-inventory.md`](https://github.com/mitodl/ol-infrastructure/blob/main/docs/plans/prek-autofix-migration-inventory.md)
in ol-infrastructure, which assigns each repository to a wave and records the findings this
contract answers. A citation such as "inventory §4.3" means item 3 of that document's §4.
**Status:** draft, 2026-09-28. Applies to every pilot and rollout PR.

This is the normative contract every repository migration follows. **MUST** and
**MUST NOT** are requirements. A PR that cannot meet one says so, gives the reason, and gets
explicit reviewer sign-off. **SHOULD** is a default that a PR may depart from, with a stated
reason.

The reference workflow templates in [`workflow-templates/`](../workflow-templates/) and the
[playbook](prek-autofix-playbook.md) implement this contract. §11 records what that work
settled.

---

## 1. Decisions

| # | Decision | Decided by |
| --- | --- | --- |
| D1 | Keep `.pre-commit-config.yaml`. prek runs it unchanged; no migration to `prek.toml` | Issue #5805 plan |
| D2 | prek runs **once** per event, inside the workflow named `autofix.ci`. That job's check is the required check. It is not duplicated into another workflow to feed an existing `ci-gate` | Repository owner, 2026-09-28 |
| D3 | Every action is pinned by full commit SHA. Hook `rev:`s stay as tags for now | Repository owner, 2026-09-28 |
| D4 | Each migration PR fixes its repository's existing hook failures itself. No separate cleanup PR | Repository owner, 2026-09-28 |
| D5 | pre-commit.ci stays installed during the rollout. Each migration PR switches off its fix pushes (§7), so the two apps never both push to one PR | This contract |
| D6 | autofix.ci is installed on all 28 in-scope repositories at once, as selected repositories, instead of one repository per migration PR (§5) | Repository owner, 2026-09-30 |

## 2. Repository changes in a migration PR

A migration PR MUST:

1. **Keep every hook's behavior.** No hook, `rev`, `args`, `files`, `exclude`, `stages`,
   `additional_dependencies`, or top-level `exclude`/`files`/`default_*` key is added,
   removed or changed, except:
   - a change needed to fix a hook that does not load (for example, superset-marimo's
     `ruff-check` at a `rev` that predates the id);
   - deleting a `packer_fmt` hook that has no `.pkr.hcl` files to check (item 3);
   - narrowing a hook (`files`, `exclude`, `args`, `additional_dependencies`) where that is
     how item 4 is met, with the reason recorded next to the change.

   Each exception is listed in the PR body. A constraint that exists only because of
   pre-commit.ci is **not** lifted here, because pre-commit.ci keeps building the hook
   environments until the repository is deselected (§7). ol-data-platform's `dbt-core<1.12`
   pin, which exists for pre-commit.ci's 250 MiB environment cap and also applies to its
   un-skipped `sqlfluff-lint`, is the one known case. It is lifted in §7 step 4.
2. **Handle the `ci:` block by installation status** (inventory §5 lists the 14 in-scope
   repositories in the pre-commit.ci installation):
   - *In the installation:* replace it with the interim block in §7. Keep its existing
     `skip` list and any `autoupdate_*` keys verbatim: pre-commit.ci's autoupdate keeps
     running until the repository is deselected, and smoot-design's `autoupdate_commit_msg`
     keeps those PR titles passing its Conventional Commits check. The block is removed after
     the repository leaves the installation.
   - *Outside it:* delete the block. Nothing reads it today, and five of these repositories
     still carry one.
3. **Run every hook in CI, including those in the old `ci: skip` list.** Those hooks never
   ran in pre-commit.ci, and some never ran anywhere (inventory §4.2). The workflow installs
   whatever they need: Node and the repository's JS dependencies, Docker, `packer`. A
   `packer_fmt` hook with no `.pkr.hcl` files to check MAY be deleted instead.
4. **Leave the default branch clean.** `prek run --all-files` passes on the PR head (D4).
   Autofixable drift is committed in the PR. Non-fixable failures are fixed, or the hook is
   narrowed with the reason recorded next to it in the config and in the PR body.
5. **Swap the tooling.** Replace `pre-commit` with `prek` in manifests, scripts, CI steps and
   developer docs:
   - `pyproject.toml` dev dependencies: `pre-commit` → `prek`, then relock with `uv lock`.
   - Developer scripts that call `pre-commit` (inventory §4.4: the two `generate_openapi.sh`
     scripts) call `prek` with the same arguments.
   - CI steps that run individual hooks outside `autofix.ci` violate D2 once the `prek`
     check is required. lehrer's `fast-checks` job runs three hooks this way
     (`ci.yml:29-31`). The migration PR switches those steps to `prek`. A lehrer PR deletes
     them, merged right after the ol-infrastructure PR that makes `prek` required (§6) has
     applied. Until then they are the only CI enforcement of those hooks. The final fleet
     audit checks that no hook runs outside `autofix.ci`.
   - README, CONTRIBUTING and AGENTS/CLAUDE files that mention pre-commit (inventory JSON
     `doc_refs`).
6. **Add the workflow** described in §3, as `.github/workflows/autofix.yml`.

A migration PR MUST NOT convert the config to `prek.toml`, add new hooks, or change hook
`rev`s beyond the exceptions above. Those are separate PRs.

### 2.1 Local installation

The prek version is pinned exactly in one place per repository, and local runs and CI both
read it from there:

| Repository kind | Pin | Local install | Local run |
| --- | --- | --- | --- |
| Python with `uv` | `prek==X.Y.Z` in a `prek` dependency group that `dev` includes (`{include-group = "prek"}`), locked in `uv.lock` | `uv sync` | `uv run prek run --all-files` |
| Node | `@j178/prek` exact version in `devDependencies`, locked | `yarn install` / `npm ci` | `npx prek run --all-files` |
| Neither | `prek-version: X.Y.Z` in the workflow | `uv tool install prek==X.Y.Z` (or brew/standalone, same version) | `prek run --all-files` |

Developers who already have pre-commit's git hook installed replace it with `prek install -f`.
Docs MUST give that command.

## 3. The workflow

### 3.1 Required properties

| Property | Requirement |
| --- | --- |
| Workflow name | MUST be exactly `autofix.ci`. The action refuses to run under any other name (`GITHUB_WORKFLOW !== "autofix.ci"` in its source), because the autofix.ci server uses the name to authenticate the fix artifact |
| Triggers | `pull_request`, and `push` to the repository's default branch (`master` in mitxpro, ocw-studio, odl-video-service and open-discussions). MUST NOT use `pull_request_target` or `workflow_run`. Add `merge_group` if a repository adopts a merge queue (none does today) |
| Permissions | Top-level `permissions: {contents: read}`. No job widens it. No secrets are referenced |
| Checkout | Pinned `actions/checkout`. `persist-credentials: false` in public repositories. Private repositories MUST keep the default (read-only token persisted), because the action runs `git fetch origin <head sha>`, which fails without credentials there. That single zizmor finding is suppressed inline with this reason |
| Pinning | Every `uses:` is a full 40-character commit SHA with a `# vX.Y.Z` comment. No tags, no branches |
| Dependencies | Toolchains and prek are installed from lockfiles or exact pins only: `uv sync --frozen`, `yarn install --immutable`, `npm ci`. No floating installs such as `pip install prek` (django-aqueduct does this today). Hook environments are built from the config's `rev`s and `additional_dependencies`, which several configs leave unpinned (for example `pydantic` on ol-data-platform's mypy). That is unchanged from pre-commit.ci and outside a migration PR's scope (§2 item 1). A PR SHOULD NOT loosen them, and a separate PR MAY pin them |
| prek version | Read from the repository's single pin (§2.1). uv repositories install only the `prek` group (`uv sync --frozen --only-group prek`), so CI does not build the whole dev environment and uv checks the wheel's hash against `uv.lock`. Node repositories take it from `node_modules/.bin` after the lockfile install. `j178/prek-action` with an exact `prek-version` is used only where neither exists |
| Concurrency | `group: autofix-${{ github.event.pull_request.number \|\| github.ref }}`, `cancel-in-progress: true` |
| Timeout | `timeout-minutes` set on the job |
| Clean-tree guard | Immediately before the first prek pass, `git status --porcelain` is empty. The action stages everything with `git add --all`, untracked files included, so anything a setup step leaves in the tree would otherwise be committed by the bot |
| Two passes | Pass 1 runs `prek run --all-files` and may modify files; its exit status is not used. Pass 2 runs `prek run --all-files --show-diff-on-failure` and MUST exit 0. Pass 2 failing means a non-fixable failure or hooks that do not converge. The job fails, and the fix step does not run |
| One fix step | `autofix-ci/action` is the job's last step, with `fail-fast: false` set explicitly. (The default, `true`, cancels every other workflow on the commit when a fix starts. That includes required checks such as `ci-gate`, which stay cancelled if no bot commit follows. The pilots measure whether `true` is worth enabling.) It runs only when pass 2 succeeded and the event is `pull_request`. On `push`, a dirty tree after pass 2 fails the job instead (`git status --porcelain` is non-empty, which also catches new generated files), because the default-branch ruleset would reject a bot push there |
| No hook skipping | `SKIP` is not set in CI |

### 3.2 Sketch

Illustrative only. The real files are the templates in
[`workflow-templates/`](../workflow-templates/), which the playbook explains.

```yaml
name: autofix.ci  # autofix.ci refuses any other name
on:
  pull_request:
  push:
    branches: [main]  # the repository's default branch
permissions:
  contents: read
concurrency:
  group: autofix-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true
jobs:
  prek:
    name: prek  # the required-check context (§6); keep it stable
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false  # private repos: omit, see §3.1
      # Repositories with neither uv nor Node pin prek here. uv repositories use
      # setup-uv plus `uv sync --frozen`, and call `uv run --frozen prek` below.
      - uses: j178/prek-action@4e14d07f9231acabce116ccfca13b13dd9755ece # v3.0.0
        with:
          install-only: true
          prek-version: 0.5.4
      # Toolchain for local hooks goes here, lockfile-only (uv sync --frozen, yarn install --immutable).
      - name: Tree is clean before hooks run
        run: test -z "$(git status --porcelain)"
      - name: prek (fixing pass)
        run: prek run --all-files || true
      - name: prek (must converge)
        run: prek run --all-files --show-diff-on-failure
      - name: Default branch has no fixable drift
        if: github.event_name != 'pull_request'
        run: test -z "$(git status --porcelain)"
      - uses: autofix-ci/action@c5b2d67aa2274e7b5a18224e8171550871fc7e4a # v1.3.4
        if: github.event_name == 'pull_request'
        with:
          fail-fast: false
```

## 4. Result semantics

The check is the `prek` job's conclusion. autofix.ci never turns a hook failure green.

| Situation | Pass 1 | Pass 2 | Fix step | Check on this commit | What happens next |
| --- | --- | --- | --- | --- | --- |
| Clean | pass | pass | no changes, exits 0 | **green** | — |
| Fixable only (PR) | modifies | pass | uploads the fix, then fails itself ("Autofix task started") | **red** | `autofix-ci[bot]` pushes one commit, and the check re-runs on it |
| Non-fixable | any | fail | not run | **red** | Author fixes locally. Log shows the diff |
| Not converging | modifies | modifies/fails | not run | **red** | Treated as a hook bug; the PR records it |
| Fix touches `.github/` | modifies | pass | refuses the whole fix | **red** | Author fixes locally. This happens when a formatter (yamlfmt, prettier) rewrites a workflow file |
| Fix does not apply to the PR head | modifies | pass | fails with a git cherry-pick error | **red** | The action computes fixes on the checked-out merge ref, then cherry-picks them onto the PR head. A conflict fails the step. Author rebases or fixes locally |
| Fixable drift on `push` | modifies | pass | not run | **red** | Someone opens a fix PR. The default branch is never bot-pushed. Until it merges, every open PR's merge ref contains the drift, so the bot adds that unrelated fix to each PR that runs. Fixing the default branch promptly is therefore part of the contract |
| autofix.ci unreachable | modifies | pass | fails with the server error | **red** | Re-run the job, or fix locally |

The fix step failing after it starts a fix is the action's own behavior (`setFailed` on a
200 response). It is what keeps the unfixed commit red.

## 5. Security properties

- **Fork PRs get no write access.** `pull_request` from a fork runs with a read-only token and
  no secrets, and this workflow uses none. The bot's commit comes from the autofix.ci app,
  never from the runner. For fork branches that do not allow maintainer edits, the app
  comments instead of pushing.
- **Workflow edits gain no privilege, but the check trusts the PR's own workflow file.** A PR
  that edits `autofix.yml` runs the edited file with the same read-only token. Through the
  bot, it can only push changes to its own branch, which its author could push anyway. The
  server refuses any fix under `.github/`. But the required `prek` check is whatever that
  PR's `autofix.yml` makes it, so a PR that changes pass 2 to `|| true` gets a green check
  with hooks failing. This is true of every Actions-based required check. Review is the
  control: each migrated repository SHOULD add `.github/workflows/` to CODEOWNERS, and
  reviewers treat any `autofix.yml` diff as a change to the gate.
- **No bot loops.** The fix step runs only after pass 2 converges. The re-run on the bot's
  commit is therefore clean and makes no further commit. The server also accepts at most one
  fix per run. Runs on the bot's commits MUST NOT be skipped: the required check has to
  report on the final head commit.
- **Pinned supply chain.** Action SHAs are pinned (§3.1). Hook environments come from the
  config's `rev`s plus `additional_dependencies`, the same inputs pre-commit.ci used (D3).
- **App scope.** autofix.ci is installed on selected repositories only (D6): the 28
  in-scope repositories (the pilot, complex and standard waves in inventory §3.1) and
  ol-github-workflows. Being in the installation does nothing by itself. The app pushes only
  when the repository runs a workflow named `autofix.ci` that calls the action, so a
  repository gets fixes from the PR that adds `autofix.yml` onward, and a migration PR needs
  no installation step. The installation is never switched to all repositories. That would
  extend the app's write access to every private repository, and to every repository
  created later, and would stop §9 step 4 from removing a single repository. A repository
  outside the 28, such as an already-prek repository adopting autofix.ci, is added by an org
  owner before its PR opens. The app requests `contents`, `actions`, `pull_requests` and
  `checks` write, and no `workflows`. The install task recorded what it actually requested
  at install time.

## 6. Required checks

- The required context is **`prek`** in every repository: the templates are copied, and the
  job is named `prek`. A reusable workflow would have produced `<caller job> / <called job>`,
  which `bin/github-required-checks` cannot score: `_defines` matches only an exact job name
  or the matrix form `<name> (`, so `sample` reports such a name as ABSENT, and `drift` fails
  on it.
- Required checks are declared in ol-infrastructure,
  `src/ol_infrastructure/saas/github/repositories/data/repos/<repo>.yaml` under
  `required_status_checks`, and applied by that stack. Nothing is set by hand in the UI.
- A repository's context is added only after its migration PR has merged, in an
  ol-infrastructure PR that declares it in the repository's YAML. Before that PR applies:
  - `uv run bin/github-required-checks sample <repo> --prs 40` marks it SAFE on at least 20
    eligible merged PRs. (That file's own evidence is that 20 sampled PRs are not enough to
    clear a name.) A low-traffic repository that cannot reach 20 within 30 days needs the
    owner's explicit sign-off, recorded in the PR.
  - `uv run bin/github-required-checks blocked <repo>` is run **on that branch**, after the
    YAML declares the context. `blocked` reads only declared contexts, so run earlier it
    checks nothing and exits 0. It must name no open PR. PRs branched before the migration
    do not contain the workflow and would hang until rebased.
- Existing required checks (`ci-gate`, `openapi-diff`, `fast-checks`, `gate`, `test`) stay.
  None of them names pre-commit.ci (inventory §4.9), so nothing needs removing.

## 7. Coexisting with pre-commit.ci, and the per-repository cutover

pre-commit.ci has no way to be switched off from config, but `autofix_prs: false` stops its
fix pushes while its checks keep reporting.

This section applies only to the 14 in-scope repositories in the pre-commit.ci installation
(inventory §5). For the other 14, pre-commit.ci does nothing today: the migration PR deletes
the `ci:` block (§2 item 2) and step 2 still applies. Step 1's interim block, step 3 and
step 4 do not. The installation's 8 archived repositories are read-only and need nothing before the
uninstall.

Each repository in the installation follows this order:

1. **Migration PR.** It sets the interim block, keeping the existing `skip` list:

   ```yaml
   ci:
     autofix_prs: false  # autofix.ci owns fix commits; remove this block after pre-commit.ci is deselected
     skip: [...]         # unchanged from before the migration
     # any existing autoupdate_* keys, unchanged
   ```

   The repository is already in the autofix.ci installation (§5). On this PR, and on every
   PR after merge, only autofix.ci pushes fixes. pre-commit.ci keeps validating the other open
   PRs, so there is no validation gap.
2. **After merge,** the required check is added (§6).
3. **An org owner deselects** the repository from the pre-commit.ci installation. Its weekly
   autoupdate stops at this point, so Renovate coverage (§8) MUST already be in place.
4. **Cleanup.** A follow-up PR removes the interim `ci:` block and lifts any
   pre-commit.ci-only constraint (ol-data-platform's `dbt-core<1.12`). The GitHub App cutover
   task owns these PRs, one per repository, and they merge before pre-commit.ci is
   uninstalled. The final fleet audit checks that none remain.

This departs from "remove the pre-commit.ci-only `ci:` keys" in the migration PR itself: the
keys are removed in step 4 instead, which is what avoids both the gap and duplicate pushes.

## 8. Update automation

- **Hook `rev`s:** Renovate's `pre-commit` manager, enabled by the org preset
  (`mitodl/.github:renovate-config.json`). Every migrated repository MUST extend the preset
  or enable the manager itself before step 3 of §7. ol-data-platform, alerting-omnibus and
  superset-marimo do neither today (inventory §4.3).
- **Action SHAs:** the preset extends `config:best-practices`, which includes
  `helpers:pinGitHubActionDigests`. Renovate keeps digests pinned and bumps them. Nothing to
  add per repository.
- **prek version:** covered automatically where it is locked (`uv.lock`, `package.json`).
  Where it lives in a workflow's `prek-version:` input, Renovate's `github-actions` manager
  updates it natively
  (renovatebot/renovate
  [`323dfea8ef`](https://github.com/renovatebot/renovate/commit/323dfea8ef145fc197bacfe26b7bd32f36d9001a),
  on main since 2026-09-15), as it does `setup-uv`'s `version`. No preset change is needed.
  No pilot uses the standalone template, so the first repository that does confirms this on
  its Renovate dashboard.
- **pre-commit.ci autoupdate** ends when a repository is deselected. Until then it duplicates
  Renovate's hook PRs in 9 repositories, as it does today.

## 9. Rollback

Per repository, in this order:

1. Remove the context from `required_status_checks` and apply. A required check whose
   workflow is gone blocks every PR. Where `prek` is the repository's only declared context,
   removing it deletes the ruleset resource, which the stack creates with `protect=True`
   (`rulesets.py`). Run `pulumi state unprotect` on that resource first, or the apply fails
   and the check stays required.
2. In a repository in the pre-commit.ci installation, restore its pre-migration `ci:` block,
   including its `skip` list, taken from the migration PR's base. (Elsewhere there is
   nothing to restore.) Without the `skip` list, pre-commit.ci tries to run hooks it
   cannot build. Delete `autofix.yml`. This is a new PR, not a revert: a revert also undoes
   the D4 drift fixes, and after §7 step 4 it no longer applies cleanly. pre-commit.ci
   resumes fix pushes once it merges.
3. If the repository was already deselected, an org owner re-adds it to the pre-commit.ci
   installation.
4. Remove the repository from the autofix.ci installation. The prek manifest and doc changes
   MAY stay, because prek also runs the config locally. If the repository migrates again
   later, an org owner adds it back before that PR opens (§5).

Fleet-wide: do steps 1–3 for every migrated repository before uninstalling autofix.ci.
Without the app, the fix step fails on every fixable PR.

## 10. Evidence

### 10.1 Each pilot PR

Link a workflow run for each of the following:

1. A clean head: green.
2. A seeded fixable change: red, exactly one `autofix-ci[bot]` commit, green on that commit.
3. A seeded non-fixable failure: red, no bot commit.
4. A seeded formatter change under `.github/`: red, fix refused.
5. A fork PR (public pilots): no write from the runner, and the app behaves as the
   maintainer-edit setting says.
6. Two pushes in quick succession: the older run is cancelled.
7. Runtime next to pre-commit.ci's on the same commit.
8. `bin/github-required-checks sample` output before the check is required.
9. On a fixable PR, what happened to the other workflows on the unfixed commit with
   `fail-fast: false`, and whether `true` would have saved runner time without leaving a
   required check cancelled.
10. A fixable change in a PR whose base branch has moved, showing the cherry-pick onto the
    PR head (§4).

Also record what the autofix.ci app requested at install time.

### 10.2 Each rollout PR

- A link to the green run on the PR head.
- The hooks from the old `ci: skip` list that now run, and what they needed installed.
- The drift fixed under D4, and any hook narrowed, with reasons.
- The exceptions to §2 item 1, or "none".
- Confirmation that Renovate covers the repository's hooks.
- For private repositories, that checkout keeps credentials (§3.1).

## 11. Settled by the reference workflow

- **Copied template, not a reusable workflow.** A reusable workflow's check name cannot be
  scored by `bin/github-required-checks` (§6), it would still need a per-repository caller for
  toolchain steps, and whether `GITHUB_WORKFLOW` inside a called workflow satisfies the
  action's name check was never verified. The required context is `prek`.
- **prek 0.5.4**, pinned per §2.1. uv 0.12.20 and Node 24.21.0 are pinned in the templates.
- **Caching:** `actions/cache` keyed on `.pre-commit-config.yaml` for prek's hook environments
  in the uv and Node templates, and prek-action's built-in cache in the standalone one.
  Toolchains for Node, Docker, packer and the project environment are in the playbook §3.
- **Renovate:** no preset change (§8).
- **Tests:** `tests/test_templates.py` asserts §3.1 and §5 on every template, and runs the
  templates' own steps against fixture repositories for every row of §4 except the
  server-side ones (the cherry-pick, the server being unreachable). The autofix action's
  decision is emulated from its source. What only a live run can show (the bot's single
  commit, fork PRs, concurrency cancellation) is the pilots' evidence (§10.1).
