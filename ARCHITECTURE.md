# dbt Assignment Grader — Architecture

A GitHub Action that statically checks a student's dbt project against a rubric. No dbt execution, no database — just file inspection.

---

## How it works

1. The action checks out the student's repo and installs the grader package.
2. `grader/main.py` reads the assignment rubric from a YAML file.
3. For each objective, `grader/checks.py` inspects files in the student's project directory.
4. Results are written to the GitHub step summary, action outputs, and optionally a PR comment.

---

## File structure

```
grader/
  checks.py       — check type models + all check implementations
  main.py         — entry point, evaluation loop, reporting
  levels/
    level_01.yml  — assignment rubric
action.yml        — composite action definition
pyproject.toml    — package metadata (pydantic, pyyaml only)
```

---

## `grader/checks.py`

**Check type models** (Pydantic) define what each objective checks for:

| Type | What it checks |
|------|---------------|
| `has_mart_model` | At least one `fct_*` or `dim_*` `.sql` file exists under `models/` |
| `has_tests` | Test count and types in schema YAML files (min/max, required types, min business logic tests) |
| `has_documentation` | Models and/or columns have `description:` fields in schema YAML |
| `has_writeup` | A markdown file exists with a minimum number of bullet points |
| `has_ref_call` | A specific `{{ ref('model') }}` call appears in a SQL file |
| `file_contains` | A regex pattern matches anywhere in a file |
| `no_hardcoded_refs` | No `schema.table` references after FROM/JOIN (ref() required) |
| `has_test` | A specific test type exists on a specific column in schema YAML |
| `has_freshness_config` | A source table has `warn_after` and `error_after` freshness config |

`run_check(objective, project_dir)` dispatches to the correct implementation and returns a `CheckResult(passed, reason)`.

---

## `grader/main.py`

Reads four environment variables (set by `action.yml`):

| Variable | Purpose |
|----------|---------|
| `GRADER_LEVEL` | Which rubric to load (e.g. `"1"` or `"level_01"`) |
| `GRADER_PROJECT_PATH` | Path to the student's project within the repo |
| `GRADER_GITHUB_TOKEN` | Automatically set from `github.token` — no user input needed |
| `GRADER_FAIL_ON_INCOMPLETE` | Exit 1 on failures, or always exit 0 |

Outputs written:
- **Step summary** — Markdown table of pass/fail per objective
- **Action outputs** — `passed`, `passed-count`, `total-count`, `level-id`, `failed-objectives`
- **PR comment** — Same Markdown table (with an HTML marker), created or updated on `pull_request` when a token is available; PR number is read from `GITHUB_EVENT_PATH`

---

## `grader/levels/level_01.yml`

Defines the assignment rubric. Each objective has an `id`, `label`, `hint`, and a `check` block whose `type` maps to one of the check models above.

To create a new assignment, add a new `level_NN.yml` and pass `level: N` in the action call.

---

## `action.yml`

Composite action (no Docker). Runs on the GitHub-hosted runner:

1. `actions/setup-python@v5` — Python 3.12
2. `pip install -e ${{ github.action_path }}` — installs the grader (deps from `pyproject.toml`)
3. `python -m grader.main` (`id: run_grader`) — runs the grader; hyphenated outputs are exposed via bracket notation in `action.yml` (`outputs['passed-count']`, etc.)

---

## Adding a check type

1. Add a Pydantic model in `checks.py` and include it in the `ObjectiveCheck` union.
2. Add an `if c.type == "your_type":` block in `run_check()`.
3. Use the new type in a level YAML.
