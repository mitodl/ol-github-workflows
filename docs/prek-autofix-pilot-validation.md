# prek + autofix.ci pilot validation

**Contract:** [`prek-autofix-contract.md`](prek-autofix-contract.md) · **Playbook:**
[`prek-autofix-playbook.md`](prek-autofix-playbook.md)
**Issue:** [mitodl/ol-infrastructure#5805](https://github.com/mitodl/ol-infrastructure/issues/5805)
**Status:** proposed 2026-09-30. Sign-off pending (§7).
**Scope update, 2026-10-01:** contract D8 dropped superset-marimo, ol-rootly-manager and
ocw_oer_export after this gate was written. The rollout it recommends (§6) is therefore 18
repositories, not 21, and the §5 row for ol-rootly-manager and the §5.1 rows for
superset-marimo no longer apply. Of the §4.1 follow-ups, the first is done: an org owner
removed all six dropped repositories from the autofix.ci installation on 2026-10-01. The
second, the inventory move, is
[ol-infrastructure#6125](https://github.com/mitodl/ol-infrastructure/pull/6125). The rest of
this record is unchanged.

This is the gate between the three pilots and the fleet rollout. It checks what the pilots
merged against the contract, records what is still open, and lists the per-repository
exceptions the rollout PRs have to handle. The merged files, hook results and `prek` job
timings were re-checked against the default branches and workflow runs on 2026-09-30. The
pre-commit.ci timings and the fixture-PR results come from the pilots' evidence comments,
linked below.

| Pilot | Migration PR | Merged | Template | §10.1 evidence |
| --- | --- | --- | --- | --- |
| ol-infrastructure | [#6092](https://github.com/mitodl/ol-infrastructure/pull/6092) | 2026-09-30 15:34 | uv + `setup-packer` | [items 1–7, 9, 10](https://github.com/mitodl/ol-infrastructure/pull/6092#issuecomment-5899323265) |
| ol-data-platform | [#2781](https://github.com/mitodl/ol-data-platform/pull/2781) | 2026-09-30 | uv | [items 1–3, 7](https://github.com/mitodl/ol-data-platform/pull/2781#issuecomment-5917716419) |
| smoot-design | [#264](https://github.com/mitodl/smoot-design/pull/264) | 2026-09-30 21:34 | Node | [items 1–3, 7](https://github.com/mitodl/smoot-design/pull/264#issuecomment-5917716824) |

The template mechanics (items 4–6, 9, 10) were shown live once, on ol-infrastructure and on
this repository's fixture PRs #5–#9. They do not depend on the repository.

---

## 1. Compatibility matrix

✅ met, ⚠ met with a recorded gap, ⏳ not yet measurable, ❌ not met.

| # | Gate criterion | ol-infrastructure | ol-data-platform | smoot-design |
| --- | --- | --- | --- | --- |
| 1 | Hook set unchanged (contract §2 item 1) | ✅ | ✅ | ✅ |
| 2 | Every old `ci: skip` hook now runs and passes | ✅ `packer_fmt`, `hadolint-docker` | ⚠ `sqlfluff-fix` passes, but lints no files ([#2782](https://github.com/mitodl/ol-data-platform/issues/2782)) | ✅ `eslint`, `prettier` |
| 3 | Every action pinned by full SHA with a version comment | ✅ 5/5 | ✅ 4/4 | ✅ 4/4 |
| 4 | `contents: read` only, no secrets, no `pull_request_target`/`workflow_run`, no `SKIP` | ✅ | ✅ | ✅ |
| 5 | Shared steps identical to the template (`tests/test_templates.py`) | ✅ | ✅ | ⚠ no package cache (§3) |
| 6 | Fork PR: read-only token, bot commit from the app | ✅ [#6097](https://github.com/mitodl/ol-infrastructure/actions/runs/36632743107) | template | template |
| 7 | Workflow edits: review is the control (contract §5) | ⚠ no CODEOWNERS | ⚠ no CODEOWNERS | ⚠ no CODEOWNERS |
| 8 | One bot commit, then green, no second commit | ✅ | ✅ | ✅ |
| 9 | Concurrency cancels the older run | ✅ [#6094](https://github.com/mitodl/ol-infrastructure/actions/runs/36632600333) | template | template |
| 10 | Non-fixable failure stays red with no bot commit | ✅ | ✅ | ✅ |
| 11 | Fix under `.github/` refused | ✅ [#6095](https://github.com/mitodl/ol-infrastructure/actions/runs/36633200290) | template | template |
| 12 | Base moved: fix cherry-picked onto the PR head | ✅ [#6096](https://github.com/mitodl/ol-infrastructure/actions/runs/36632696912) | template | template |
| 13 | Push to the default branch: green, no bot push | ✅ | ✅ | ✅ |
| 14 | Required context is `prek` | ✅ emitted; ⏳ §6 sample | ✅ emitted; ⏳ §6 sample | ✅ emitted; ⏳ owner sign-off |
| 15 | Renovate covers hook `rev`s (contract §8) | ✅ org preset | ⚠ repository config; `additional_dependencies` not covered (§4.3) | ✅ org preset |
| 16 | Runtime comparable to pre-commit.ci | ✅ §2 | ✅ §2 | ✅ §2 |
| 17 | Rollback (contract §9) | documented, not exercised | documented, not exercised | documented, not exercised |
| 18 | Private-repository behavior | not a pilot | not a pilot | not a pilot. Out of scope (§4.1) |

**How rows 1–5 and 13 were checked.** Row 1 diffs `.pre-commit-config.yaml` between each
migration PR's base and merge commit: the only changes are the interim `ci:` block's
`autofix_prs: false` and, in ol-infrastructure, one comment. Row 2 reads the per-hook
results from pass 2 of a post-merge push run on each default branch. ol-infrastructure passes
19 of 19 hooks, ol-data-platform 16 of 16, and smoot-design 14 of 14, with `check-toml` and
`debug-statements` reporting "no files to check". Rows 3–5 run this repository's
`tests/test_templates.py` with each pilot's `autofix.yml` standing in for its template:

| Pilot copy tested as | Result | The one failure |
| --- | --- | --- |
| ol-infrastructure → `autofix-uv.yml` | 62 of 63 pass | `test_this_repository_runs_the_uv_template` checks this repository's own workflow, so it does not apply |
| ol-data-platform → `autofix-uv.yml` | 62 of 63 pass | Same |
| smoot-design → `autofix-node.yml` | 62 of 63 pass | `test_node_template_caches_packages_before_installing`: the copy predates #11 (§3) |

The behavioral tests (clean, fixable, non-fixable, non-converging, setup leftovers, the
`.github/` refusal) run each pilot's own steps and pass. The yamlfmt re-indentation in the two
uv copies parses to the same YAML.

## 2. Runtime

The `prek` job's duration, from the job's own start and end times. Queue time is excluded,
which flatters pre-commit.ci's figures.

| Repository | pre-commit.ci, same commit | `prek` cold | `prek` warm (main's cache restored) |
| --- | --- | --- | --- |
| ol-infrastructure | 76 s, 2 hooks skipped | 120 s | 78–109 s, 4 runs |
| ol-data-platform | 105 s, `sqlfluff-fix` skipped, after 8 min 25 s queued | 91 s | 116–132 s, 3 runs |
| smoot-design | 7 s, `eslint` and `prettier` skipped, after 10 min 8 s queued | 108 s on the PR; 88 s on main's first push | 74 s with the Yarn cache ([#267](https://github.com/mitodl/smoot-design/pull/267), both caches restored from that PR's earlier run) |

Every warm run above restored the prek cache on its primary key. Everything outside the two
prek passes took 13–22 s in the uv repositories and 43 s in smoot-design, most of it
`yarn install`. The rest is the hooks themselves, run twice. Pass 2 takes 15–51 s of every
run, including clean ones, where it repeats a pass that already succeeded. ol-data-platform's
warm runs were no faster than its cold one; both passes took longer, and this gate did not
isolate why. §4.3 records the pass-2 cost as an option, not a defect.

Against pre-commit.ci the comparison is favorable once queueing is counted: pre-commit.ci
queued 8–10 minutes on the two lower-traffic pilots, and it skipped the hooks that cost the
most.

## 3. Defects found and resolved before this gate

| Finding | Resolution |
| --- | --- |
| uv `exclude-newer` blocks the prek pin | Playbook §2 step 2: exempt prek (`prek = "0d"`) ([#11](https://github.com/mitodl/ol-github-workflows/pull/11)) |
| A YAML formatter reformats the copied template, and autofix.ci refuses fixes under `.github/` | Playbook §2 step 4: commit the formatted copy (#11) |
| Node job spent 61 of 108 s in an uncached `yarn install` | Node template caches Yarn's download cache, keyed on `yarn.lock` (#11). **smoot-design's copy predates it.** Its follow-up is tracked with the smoot-design cutover (contract §7 step 4) |
| A passing hook can lint nothing (ol-data-platform sqlfluff) | Playbook §2 step 5: seed a violation per linting hook. ol-data-platform's own gap is [#2782](https://github.com/mitodl/ol-data-platform/issues/2782) |
| `hadolint-docker` runs the untagged image | Playbook §3.3: `docker pull` before measuring. Pinning the image is a hook change, outside migration PRs |
| PR runs start cold until main saves the cache | Playbook §7. The first push to main saved the prek cache in all three pilots, and later PR runs in ol-infrastructure and ol-data-platform restored it |

## 4. Open items

### 4.1 Private repositories: dropped from scope (decided)

autofix.ci is free for open-source repositories only. Its GitHub Marketplace listing prices
private repositories on organization accounts at $10/month (Startup, up to 20 users) or
$50/month (Pro, up to 200 users). mitodl has 38 members, so Pro would be needed. No pilot is
private, so this was never exercised. On the free plan, a private repository's fixable PRs
would hit the "autofix.ci unreachable" row of contract §4. The check is the job's conclusion,
so they would stay red until fixed locally. Clean PRs never reach the server and non-fixable
failures never run the fix step, so those two cases would be unaffected.

The three private in-scope repositories are **access-forge, alerting-omnibus and hq**. On
2026-09-30 the owner chose to drop them from scope (contract D7), rather than buy Pro or give
them a check-only workflow. None of them is in the pre-commit.ci installation, so nothing
enforces their hooks today and dropping them removes no gate. Two follow-ups:

- An org owner removes them from the autofix.ci installation, which D6 had added them to. The
  app keeps `contents: write` there until then.
- The inventory in ol-infrastructure moves them to its §6 exclusions, with this decision
  as the reason.

The contract's private-repository branches (§3.1 checkout credentials, §10.2) stay. A
private repository that adopts the workflow later needs the plan decided first.

### 4.2 Not yet observable

- **Required checks (contract §6).** These are tracked per pilot as cutover tasks. `sample`
  must report `prek` SAFE on at least one eligible merged PR, and `gh pr checks` must show
  a successful `prek` conclusion on an eligible PR. The owner will monitor for problems
  after rollout.
- **Renovate after an autofix commit.** Renovate PRs in ol-infrastructure have run green
  without needing a fix. Across the three pilots, no PR updated since the merges carries an
  `autofix-ci[bot]` commit apart from the two fixture PRs. So whether Renovate stops
  rebasing a PR that received one, for example from `sync-version-pins`, is still unseen
  (playbook §7).
  The behavior matches pre-commit.ci's today, so this does not block the rollout.
- **Rollback.** Contract §9 is documented, not rehearsed. Its step 1 warning is accurate:
  the required-checks ruleset is created with `protect=True`
  (ol-infrastructure `saas/github/repositories/rulesets.py`). This gate fixed step 2, which
  restored only the `ci:` block. After §7 step 4 lifts ol-data-platform's `dbt-core<1.12`,
  pre-commit.ci could no longer build `sqlfluff-lint` (277 MiB against a 250 MiB cap). Step 2
  now restores such constraints too.

### 4.3 Options, not defects

- **Skip pass 2 when pass 1 exits 0.** A clean pass 1 modified nothing and failed nothing, so
  pass 2 repeats it. Skipping it would save 15–51 s on every clean run. This changes the
  shared steps and contract §3.1 ("its exit status is not used"), so it would be a template
  PR with tests, not a rollout change.
- **`fail-fast: true`.** It would save about 2 runner-minutes per fixable PR in
  ol-infrastructure, but could leave `ci-gate` cancelled. Keep `false`.
- **CODEOWNERS for `.github/workflows/`** (contract §5 SHOULD). None of the three pilots has
  a CODEOWNERS file. The org `baseline-default-branch` ruleset requires one approving review
  on the default branch of every `tier-1` or `standard` repository, and every in-scope
  repository is `tier-1`. So workflow edits are reviewed anyway. They are not routed to a
  specific owner. This should be a fleet decision rather than a deviation in every PR.
- **ol-data-platform's `additional_dependencies`.** Renovate's `pre-commit` manager skips
  them where no `language:` is set. That is unchanged from pre-commit.ci, which does not
  update them either.

## 5. Exceptions for the complex wave

Each is a deviation the rollout PR has to handle. Each cites the contract or playbook
section it falls under. Wave membership and hook data come from inventory §3.1.

| Repository | Default branch | In pre-commit.ci | Template | What the PR must handle |
| --- | --- | --- | --- | --- |
| learn-ai | main | no, so delete `ci:` | uv + Node (playbook §3.1) | `scripts/generate_openapi.sh` calls prek (contract §2 item 5) |
| lehrer | main | no, so delete `ci:` | uv, full `uv sync --frozen` (playbook §3.4) | The first prek run of the `system` hooks `build-config-schema` and `build-manifest-schema`. Delete `packer_fmt` (no `.pkr.hcl`). Pull hadolint before measuring. The `fast-checks` steps switch to prek, then are deleted after `prek` is required (contract §2 item 5) |
| mit-learn | main | yes, so interim `ci:` | uv + Node | The first CI run of `style-lint` and of `check-vendor-directory` (`system`, never run under prek). `generate_openapi.sh`. Keep `ci-gate` and `openapi-diff` |
| mit-learn-api-clients | main | yes | Node | The first CI run of `eslint` |
| mitxonline-api-clients | main | no | Node | The first CI run of `eslint`. D4 drift: trailing-whitespace, end-of-file, prettier, shfmt |
| mitxpro | **master** | yes | uv + Node | `push:` on `master`. D4 drift: actionlint |
| ocw-studio | **master** | yes | uv + Node | `push:` on `master`. The first CI run of `shfmt-docker` (Docker only) |
| ol-rootly-manager | main | no | uv | Delete `packer_fmt` (no files). The first CI run of `hadolint-docker`: pull before measuring |
| platform-engineering-site | main | no | uv | Delete `packer_fmt` (no files). D4 drift: trailing-whitespace, end-of-file, yamlfmt, ruff-format, mypy |

For every Node-using repository: copy the Node steps from the template as merged in #11,
cache included. For every repository: seed a violation for each linting hook (playbook §2
step 5), and report a hook that catches nothing in the PR body.

### 5.1 Standard-wave items that are not routine

| Repository | Item |
| --- | --- |
| superset-marimo | No Renovate (contract §8). The owner confirms it is still used before a PR is spent (inventory §4.11) |
| superset-marimo | Config does not load (`ruff-check` at `v0.9.0`). The `rev` fix is allowed by contract §2 item 1 |
| odl-video-service, open-discussions | Default branch is `master` |
| open-edx-plugins | `uv-lock` rewrites `uv.lock`, so it is a generated-file hook (playbook §3.5) |
| mitxonline | `ci-gate` is required. D4 drift: actionlint |
| ol-django | Migrated ahead of the rollout in [#595](https://github.com/mitodl/ol-django/pull/595) (approved, not yet merged, on 2026-09-30): uv template, interim `ci:` block, `prek` green. It deviates only in pinning prek 0.5.3 instead of exempting 0.5.4 from `exclude-newer` (playbook §2 step 2). The PR expects Renovate to bump it once 0.5.4 clears the window. Its workflow passes the same template tests as the uv pilots. It needs only the post-merge steps: contract §6, then §7 steps 3–4 |

## 6. Verdict

The contract and templates hold on all three pilots. No hook was lost, every hook
pre-commit.ci skipped now runs, and every security property in contract §3.1 and §5 is in
place in the merged files. No reference-workflow defect remains open, and the one contract
defect found (rollback step 2, §4.2) is fixed here. The recommendation is to **approve the
rollout for the 21 remaining in-scope repositories**, with the §5 exceptions. That is the 25
in scope under D7, less the three pilots and ol-django.

One accepted exception carries forward. ol-data-platform's two sqlfluff hooks run but lint no
files ([#2782](https://github.com/mitodl/ol-data-platform/issues/2782)). That gap predates the
migration: pre-commit.ci's `sqlfluff-lint` linted nothing too. The owner kept it out of #2781,
and no other in-scope repository runs sqlfluff. Approving the rollout does not close it. Each
rollout PR's seeded-violation check (playbook §2 step 5) is what keeps the same kind of gap
from going unnoticed elsewhere.

## 7. Sign-off

| Role | Name | Date | Decision |
| --- | --- | --- | --- |
| Repository owner | | | |
