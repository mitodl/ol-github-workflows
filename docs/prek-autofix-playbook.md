# prek + autofix.ci repository migration playbook

**Contract:** [`prek-autofix-contract.md`](prek-autofix-contract.md). This playbook is how to
meet it. Where they disagree, the contract wins.
**Templates:** [`workflow-templates/`](../workflow-templates/)
**Issue:** [mitodl/ol-infrastructure#5805](https://github.com/mitodl/ol-infrastructure/issues/5805)

---

## 1. Pick a template

Each repository copies one template to `.github/workflows/autofix.yml` and changes only the
lines marked `ADAPT`. The templates are copied, not called as a reusable workflow, so the
check is named `prek` in every repository (contract §6) and each repository can add the
toolchain its local hooks need.

| The repository pins prek in | Template | prek installed by |
| --- | --- | --- |
| `uv.lock` (Python with uv) | [`autofix-uv.yml`](../workflow-templates/autofix-uv.yml) | `uv sync --frozen --only-group prek`, hash-checked against `uv.lock` |
| `package.json` + lockfile (Node) | [`autofix-node.yml`](../workflow-templates/autofix-node.yml) | `yarn install --immutable` (or `npm ci`) |
| Neither | [`autofix-standalone.yml`](../workflow-templates/autofix-standalone.yml) | `j178/prek-action` with an exact `prek-version` |

A repository with both uv and Node (mit-learn, learn-ai, mitxpro, ocw-studio) uses the uv
template and adds the Node steps from §3.1.

Everything from the clean-tree guard to the end of the file is identical in all three
templates, and [`tests/test_templates.py`](../tests/test_templates.py) enforces that. Do not
edit those steps in a repository's copy. If a repository needs a change there, change the
templates here first, so every repository and the tests stay in step.

## 2. Migration PR checklist

Work top to bottom. The contract section is in brackets.

1. **Branch from the default branch** and note whether the repository is in the pre-commit.ci
   installation (inventory §5).
2. **Pin prek once** [§2.1]:
   - uv: add the group and include it from `dev`, then `uv lock`:

     ```toml
     [dependency-groups]
     prek = ["prek==0.5.4"]
     dev = [{ include-group = "prek" }, ...]  # and remove "pre-commit"
     ```

   - Node: `yarn add -D -E @j178/prek@0.5.4` (or `npm install -D -E`), and remove
     `pre-commit` from any Python manifest the repository also has.
   - Neither: set `prek-version` in the standalone template.
3. **Handle `ci:`** [§2 item 2]. In the installation: replace the block with the interim block
   (§7 step 1), keeping `skip` and `autoupdate_*` verbatim. Outside it: delete the block.
4. **Copy the template** to `.github/workflows/autofix.yml` and apply its `ADAPT` lines:
   - the default branch under `push:`
   - private repositories: delete checkout's `with: persist-credentials: false` block, and add
     `# zizmor: ignore[artipacked]` on the `uses:` line with the reason (contract §3.1)
   - toolchains for the local hooks and the old `ci: skip` hooks (§3)
5. **Make the tree clean** [§2 item 4, D4]: `uv run prek run --all-files` (or `npx prek`)
   until it passes. Commit the autofixes. Fix or narrow what does not autofix, and record
   each narrowing next to the hook and in the PR body.
6. **Swap the tooling** [§2 item 5]: scripts and CI steps that call `pre-commit` call `prek`;
   README, CONTRIBUTING, AGENTS/CLAUDE files say `prek` and give `prek install -f`.
7. **Check Renovate coverage** [§8]: the repository extends
   `local>mitodl/.github:renovate-config` or enables the `pre-commit` manager itself.
8. **Check the autofix.ci installation** (contract §5). The 28 in-scope repositories are
   already in it, unless a rollback removed one (contract §9 step 4). Any other repository
   needs an org owner to add it before the PR opens, or the fix step fails on every fixable
   PR. Only an org owner can see the installation's repository list, so if the first fixable
   run fails at the fix step with an installation error, ask one to check.
9. **Open the PR** with the evidence in contract §10.2 (§10.1 for pilots).
10. **After merge:** declare the `prek` check in ol-infrastructure (contract §6), then the
    pre-commit.ci deselect and cleanup (contract §7 steps 3–4).

## 3. Toolchains

Add these after the prek install and cache steps and before `Tree is clean before hooks run`.
Everything installs from a lockfile or an exact pin. The clean-tree guard fails the job if a
step leaves files in the working tree. That is deliberate: autofix.ci would commit them.

### 3.1 Node in a uv repository

For local `language: node` hooks (prettier, eslint, stylelint) that use the repository's own
`node_modules`:

```yaml
      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0
        with:
          node-version: "24.21.0" # or node-version-file, if the repository pins Node
      - name: Install JS dependencies from the lockfile
        run: |
          corepack enable
          yarn install --immutable
```

If the JS project is in a subdirectory, add `working-directory:` to the install step.

### 3.2 packer

For `packer_fmt` where the repository has `.pkr.hcl` files. Where it has none, delete the hook
instead (contract §2 item 3).

```yaml
      - uses: hashicorp/setup-packer@ce93c3c08a6c2ff2275bf4b54ff0d9a75f6c9789 # v3.4.0
        with:
          version: "1.14.2"
```

### 3.3 Docker

`hadolint-docker` and `shfmt-docker` need nothing: GitHub-hosted Ubuntu runners have Docker.

### 3.4 The project environment

`language: system` hooks that import the project (lehrer's `build-config-schema` and
`build-manifest-schema`) need the full environment. In the uv template, replace
`uv sync --frozen --only-group prek` with `uv sync --frozen`. `.venv/bin` is already on
`PATH`, so the hooks' `python` resolves to it.

### 3.5 Generated files

Hooks that write generated files (`sync-version-pins`, `uv-lock`, the lehrer schema builders)
run in pass 1 like any fixer. autofix.ci commits what they write, and pass 2 proves the
output is stable. A generator that is not deterministic fails pass 2. Fix the generator; do
not skip the hook.

## 4. Local use

```bash
uv sync                     # or yarn install / npm ci
uv run prek install -f      # replaces a pre-commit git hook, if one is installed
uv run prek run --all-files
```

In Node repositories, use `npx prek` in place of `uv run prek`.

## 5. What the check does

The job is the required check `prek`. Contract §4 is the full table. In short:

- **Clean:** green.
- **Fixable, on a PR:** red, and autofix.ci pushes one commit. The check re-runs on that
  commit and is green.
- **Anything that does not autofix,** or hooks that keep changing files: red, no commit. The
  log shows the diff.
- **Fixable, on the default branch:** red, and the log shows the diff. Open a PR with it.
- **A fix under `.github/`:** red, fix refused. Run prek locally and commit.

## 6. Updating pinned actions and tools

Renovate does this through the org preset. It covers action SHAs (`helpers:pinGitHubActionDigests`),
`setup-uv`'s `version`, `prek-action`'s `prek-version`, `setup-packer`'s `version`, and the
prek pin in `uv.lock` or `package.json`. Its `github-actions` manager reads both
`.github/workflows/` and `workflow-templates/`. Each migrated repository gets its own bump
PRs, so there is nothing to propagate by hand.

To bump an action manually, for example because a security fix cannot wait for the preset's
14-day minimum release age:

1. Resolve the release tag to its commit, and confirm the commit is on the action's own
   repository, not a fork:

   ```bash
   gh api repos/<owner>/<action>/commits/<tag> --jq .sha
   gh api repos/<owner>/<action>/compare/<old-sha>...<new-sha> --jq .status  # ahead
   ```

2. Read the diff between the two commits, and the changelog. For `autofix-ci/action`,
   re-check the behaviors the contract depends on: the `autofix.ci` name check, `git add --all`,
   the `.github` refusal, `setFailed` after a started fix, and the `git fetch` of the PR
   head.
3. Replace the SHA and the `# vX.Y.Z` comment in **every** template here and in this
   repository's own workflows. `test_all_templates_pin_the_same_commit_per_action` fails if
   one is missed.
4. Run `uv run pytest` and `uv run prek run --all-files`, and open a PR.
5. Repositories that already copied the template get the same bump from Renovate. For an
   urgent fix, open those PRs directly.

## 7. Known limits

- **Standalone downloads are not checksum-verified.** `j178/prek-action` v3.0.0 carries
  SHA-256s only for prek 0.4.11 and older. The uv and Node templates install prek from a
  lockfile with a verified hash, which is why they are the default.
- **Renovate PRs get autofix commits.** A hook that rewrites files after a bump (for example
  `sync-version-pins`) makes autofix.ci push to Renovate's branch. The pilots record whether
  Renovate then stops rebasing that PR.
- **Only simulated here:** the tests run the templates' steps and emulate the action's
  decision. What the autofix.ci server does (one commit, fork handling, maintainer-edit
  settings) and real concurrency cancellation are recorded by the pilots (contract §10.1).
