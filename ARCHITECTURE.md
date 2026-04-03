# dbt Assignment Grader — Architecture

A GitHub Action that checks a student's dbt project against a rubric. Combines static file inspection with lightweight dbt parsing (no query execution, no live database connection).

---

## How it works

1. The action installs the grader package and `dbt-bigquery`.
2. `dbt deps` is run in the student's project to install declared packages.
3. The dbt Fusion binary is installed and its path exported to `$FUSION_DBT_BIN`.
4. `grader/main.py` loads the assignment rubric and runs each check via `grader/checks.py`.
5. Results are written to the GitHub step summary, action outputs, and optionally a PR comment.

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
| `has_mart_model` | A `fct_*` or `dim_*` `.sql` file exists under `models/` (configurable via `prefix`) |
| `has_tests` | Test count and types in schema YAML (min, required types, min business logic tests — no upper limit) |
| `has_documentation` | Models and/or columns have `description:` fields in schema YAML |
| `has_writeup` | A markdown file exists with a minimum number of bullet points |
| `has_ref_call` | A `{{ ref('model') }}` call appears in a SQL file |
| `file_contains` | A regex pattern matches anywhere in a file |
| `no_hardcoded_refs` | No `schema.table` references after FROM/JOIN; files with `{{ config(static_analysis='unsafe') }}` are skipped |
| `has_test` | A specific test type exists on a specific column in schema YAML |
| `has_freshness_config` | A source table has `warn_after` and `error_after` freshness config |
| `dbt_parses` | Project parses successfully using the pip-installed `dbt-core` + `dbt-bigquery` with a fake BigQuery profile |
| `dbt_fusion_parses` | Project parses successfully using the dbt Fusion binary (`$FUSION_DBT_BIN`) with a fake BigQuery profile |

**Notes:**
- Tests are collected from both `tests:` and `data_tests:` keys (supporting dbt <1.8 and ≥1.8 syntax).
- `dbt_packages/` and `target/` directories are excluded from all YAML scans so installed package tests don't pollute the results.
- Files with `{{ config(static_analysis='unsafe') }}` (e.g. metricflow time spine) are exempt from the `no_hardcoded_refs` check.
- Both parse checks create a temp `profiles.yml` using a fake BigQuery connection — no credentials or database access required.

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

Steps run on the GitHub-hosted runner in order:

1. `actions/setup-python@v5` — Python 3.12
2. **Install grader** — `pip install -e ${{ github.action_path }} dbt-bigquery`
3. **Install dbt packages** — `dbt deps` in the student's project directory (tolerates missing `packages.yml`)
4. **Install dbt Fusion** — downloads the Fusion binary via the official install script; writes the binary path to `$GITHUB_ENV` as `FUSION_DBT_BIN`
5. **Run grader** — `python -m grader.main`; hyphenated outputs exposed via bracket notation (`outputs['passed-count']`, etc.)

---

## Adding a check type

1. Add a Pydantic model in `checks.py` and include it in the `ObjectiveCheck` union.
2. Add an `if c.type == "your_type":` block in `run_check()`.
3. Use the new type in a level YAML.
