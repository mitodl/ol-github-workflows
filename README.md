# ol-github-workflows

Shared GitHub Actions workflows and workflow templates for mitodl repositories.

## Contents

| Path | What it is |
| --- | --- |
| `.github/workflows/add-to-ol-hq.yaml` | Reusable workflow that adds new issues to the Open Learning HQ project |
| `workflow-templates/autofix-*.yml` | Reference prek + autofix.ci workflows, copied into each repository as `.github/workflows/autofix.yml` |
| `docs/prek-autofix-contract.md` | The normative contract every prek + autofix.ci migration PR follows |
| `docs/prek-autofix-playbook.md` | How to migrate a repository: template choice, checklist, toolchains, pin updates |
| `docs/prek-autofix-pilot-validation.md` | The gate between the pilots and the rollout: compatibility matrix, open items, per-repository exceptions |
| `tests/` | Structural and behavioral tests for the templates |

## Development

```bash
uv sync
uv run prek install -f
uv run prek run --all-files
uv run pytest
```

This repository runs its own `workflow-templates/autofix-uv.yml` as `.github/workflows/autofix.yml`,
and the tests require the two to stay identical.
