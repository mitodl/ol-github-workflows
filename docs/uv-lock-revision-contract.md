# uv.lock revision check contract

What `actions/uv-lock-revision` and the `workflow-templates/uv-lock-revision.yml` that calls
it guarantee, and what a repository adopting them has to do. Normative.
`tests/test_uv_lock_revision.py` asserts every structural claim except the pin consistency in
§3.2 item 6, which `tests/test_templates.py` asserts across every template and action at once.

## 1. The problem

uv writes two version keys into `uv.lock`, and they carry different promises:

```toml
version = 1
revision = 5
```

`version` is the backwards-**incompatible** tier. `revision` is the backwards-**compatible**
one -- [the pull request that added it](https://github.com/astral-sh/uv/pull/11500) puts it
plainly:

> While lockfile version bumps are backwards-incompatible, older uv versions _can_ read
> lockfiles with a later revision -- they just won't understand all the data.

Any uv command that **re-resolves** rewrites `revision` to whatever the running uv natively
writes. Measured:

| Operation | Rewrites `revision`? |
| --- | --- |
| `uv lock` with no resolution change | no, preserves it in both directions |
| `uv lock --upgrade`, `uv add` | yes |
| `uv sync --frozen`, `uv run --frozen`, `uv build` | no, never writes |

The two directions it can move are not equally serious. A revision **rising** is a newer uv
writing a format an older uv still reads: a compatible extension, by uv's own definition. A
revision **falling** is the loss -- an older uv re-resolved and wrote the lockfile back
without the fields the newer format carried. uv has no flag to refuse that today
([astral-sh/uv#22911](https://github.com/astral-sh/uv/issues/22911),
[#22912](https://github.com/astral-sh/uv/issues/22912) are both open), and nothing else
catches it, because uv accepts a lockfile written by a different version:

```console
$ uv lock --check
$ uv sync --locked
```

What is true of both directions is that they are **invisible**.
[mitodl/mit-learn#4070](https://github.com/mitodl/mit-learn/pull/4070) changed one line of
`pyproject.toml`, zero package entries, and moved the lockfile from revision 3 to 5 with
nothing in the title or diff summary to say so. That is an argument for annotating the
move, not for failing it.

Asserting an exact revision failed both directions alike, and the cost was not theoretical:
uv 0.12.22 began writing revision 5 where 0.12.18 wrote 3, so every Renovate bump in a
repository still on 3 turned red -- two dozen pull requests across three repositories,
several of them security updates. A check that is wrong on every pull request is a check
someone turns off.

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

There is a blunter reason too. The re-resolve that moves the field is usually Renovate's,
and that runs in Mend's hosted environment -- no `required-version`, no `setup-uv` pin, no
setting in the repository at all reaches the uv that writes the lockfile.

So the constraint belongs on the lockfile, not on the tool: a floor on the revision says
"no uv may quietly take this backwards" directly, which is what reaching for
`required-version` was groping at.

## 3. Required properties

### 3.1 Why a composite action and not a reusable workflow

The check is a composite action, so the adopting workflow calls it as a **step** inside its
own job. A reusable workflow called with `uses:` at job level would make the check context
`<caller job> / <called job>`, renaming the required check in every repository that has
adopted it, and GitHub offers no way to collapse that to one name. The action keeps the
context at `uv.lock revision` (§3.2 item 4) and keeps the `actions/checkout` pin in one place
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
   the file; it must not be able to relock anything. The reading is done by `check.py`,
   run with the runner's own `python3` and parsing the lockfile with `tomllib` from the
   standard library, so nothing is installed. A parser rather than a scan: `1_0` is ten,
   `0x10` is sixteen, and a `version` under a `[[package]]` is that package's, none of
   which a search for the first line starting `version =` gets right.
8. `actions/checkout` sets `persist-credentials: false` and `fetch-depth: 2`, in every
   repository -- no step runs a `git` command that reaches the network. The depth is what
   lets item 14 read the base out of the checkout instead of fetching it; a fetch would
   need the credentials this checkout deliberately does not persist.
9. `expected-revision` is the single required input and names a **floor**: a lockfile at or
   above it passes. It reaches the script through `env:` rather than `${{ }}` interpolation
   inside the body, because an expression expanded into the script would be shell, and a
   caller's typo could run as one. `expected-version` is optional and defaults to `"1"`.
10. The script rejects an `expected-revision` or `expected-version` that is not a decimal
    integer before it scans anything. GitHub does not enforce `required:` on action inputs,
    so an omitted `with:` arrives as an empty string -- an empty floor, which would admit
    any revision at all, including a lockfile carrying none.
11. Every tracked path ending in `uv.lock` is checked, found with
    `git ls-files -z '*uv.lock'`, so a workspace with many lockfiles needs no extra
    configuration. The pathspec crosses `/` and matches a non-empty prefix, so a stray
    `notuv.lock` would be checked too -- it errs toward checking more, not less.
12. A repository with no `uv.lock` fails the check rather than passing vacuously.
13. **The ratchet.** A lockfile whose revision is below its own copy on the base fails even
    when it clears the floor. The floor alone cannot catch this: a repository whose floor is
    3 and whose lockfile has reached 5 would pass a rollback all the way back to 3.
14. The base is `HEAD^1` in the checkout. On a `pull_request` the ref is
    `refs/pull/N/merge`, whose first parent is the branch being merged into; on a push it is
    the previous commit. Either way it is what the change moves away from, so the script
    needs to know nothing about the event. The working tree is the merge result, so a pull
    request merely *behind* a base that moved forward does not trip the ratchet.
15. Where there is no base -- a single-commit checkout, a root commit, a lockfile the change
    adds, a path it renamed -- the check falls back to the floor alone and **says so in its
    summary line**, counting how many lockfiles it compared and how many it did not. A
    floor-only run is never reported as a full one, whether that is the whole run or one
    file of several, and a missing base never fails a pull request that is otherwise fine.
16. A revision **rising** is not a failure. A lockfile above the floor draws a `::notice`
    and the job stays green. `version` is the exception: it is uv's backwards-incompatible
    tier, so it is asserted exactly against `expected-version` and moving it is a migration.

## 4. Adoption

Copy `workflow-templates/uv-lock-revision.yml` to `.github/workflows/uv-lock-revision.yml`
and change only the `ADAPT` lines:

| Line | Change |
| --- | --- |
| `branches: [main]` | the repository's default branch |
| `expected-revision` | the lowest `revision` any `uv.lock` in the repository may be on |

The action ref carries no `ADAPT` marker. A repository that repoints it is no longer running
the shared check; Renovate keeps the pin current, as it does for every other action.

Read the current revision rather than assuming it:

```console
$ git ls-files -z '*uv.lock' | xargs -0 grep -h '^revision = ' | sort -u
revision = 5
```

More than one value is fine -- set the floor to the lowest of them. The notices will tell
you when they have converged and the floor can be raised.

Add the job to the repository's required checks once it has passed on the default branch.

This repository's own `.github/workflows/uv-lock-revision.yml` is the one copy that differs:
it calls the action by self-repository ref, `uses: $/actions/uv-lock-revision`, so a pull
request here exercises the action as the branch defines it rather than whatever is already on
`main`. `tests/test_uv_lock_revision.py::test_this_repository_runs_the_template` asserts that
its triggers, permissions, concurrency, job name and input names match the template's; the
input *values* differ on purpose, since the two repositories expect different revisions.

§3.2 items 2 and 3 are asserted against it directly rather than through that comparison. A
widened token or a `continue-on-error` reachable only in the copy this repository runs is the
one divergence a key-by-key comparison would not see. actionlint does not yet know the `$/`
syntax, so `.github/actionlint.yaml` filters the one message it produces for the one file.

## 5. Changing the check

A fix to the action reaches an adopting repository only as a Renovate bump of the pinned SHA,
and Renovate raises one only when a newer tag exists: a SHA whose comment names no tag is
[disabled by default](https://docs.renovatebot.com/modules/manager/github-actions/), because
nothing tells it what the SHA is a version of. So every change to `actions/uv-lock-revision`
needs a tag, or no repository ever receives it. Tag the merge commit and update the template's
pin and version comment in the same move.

Tags are repository-wide, so a second action here shares this one's version line and its
adopters see a bump whose behavior did not change. Group them in Renovate before reaching for
a per-action prefix: a prefixed comment such as `# uv-lock-revision/v1.0.0` does not match
Renovate's `/^v?\d+/`, which drops the dependency to the `github-digest` datasource and
digest-only updates.

## 6. Changing the format deliberately

A `revision` may rise on its own, in a Renovate pull request, carrying a `::notice` on the
diff. That annotation is the reviewable moment, and it no longer costs a red check. Raising
`expected-revision` afterwards is bookkeeping: do it once every `uv.lock` in the repository
has reached the new revision, and the floor then narrows what a stale uv can write.

**The ratchet has no in-band override.** Lowering `expected-revision` lowers the floor; it
does not license a downgrade, and a pull request that lowers both the floor and a lockfile
still fails. That is deliberate: a downgrade is the one thing this check exists to stop, so
an input that waves it through would be an input whose only purpose is to defeat the check,
left behind in the workflow afterwards. A repository that genuinely has to go backwards
removes or skips the check for that one merge, visibly, and puts it back.

`version` is the other way round. It is backwards-incompatible, so moving it is a migration:
relock and set `expected-version` in the same pull request. Nothing automated updates that
one -- a bot cannot decide an incompatible format change is intended.

## 7. What it does not do

It does not pin uv, and does not stop anyone running an old one. It reports that the
format moved, not who moved it. Repositories wanting a floor for unrelated reasons, such
as a `[tool.uv]` feature, keep setting `required-version` themselves; this check is
indifferent to it.

It does not stop a repository drifting forward, deliberately -- that is a compatible
extension, and blocking it was what turned two dozen Renovate pull requests red.

It does not look past `HEAD^1`, which has a consequence on pushes worth naming. On a pull
request that parent is the base branch tip, so the ratchet sees the whole change. On a push
it is the previous commit, so a push of several commits at once is compared only against
the first of them: a two-commit push that lowers a revision in both is compared 3 against 3
and passes. The pull request is the gate and is correct; the push run is a backstop, and a
multi-commit push straight to the default branch is already outside the review model.

A downgrade that already landed on the base branch *is* the base, and only the floor will
catch it. Nor does the ratchet follow a rename: a lockfile moved to a new path has no base
copy there, and is held to the floor alone.
