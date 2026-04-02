# dbt Assignment Grader

A GitHub Action that automatically checks a student's dbt project against an assignment rubric. No dbt execution required — it statically inspects files and reports pass/fail for each requirement.

![License](https://img.shields.io/badge/license-MIT-blue)

---

## What it checks

Each assignment rubric can include any combination of these checks:

| Requirement | What's verified |
|-------------|----------------|
| **Mart model** | At least one `fct_*` or `dim_*` `.sql` file exists under `models/` |
| **Tests** | Schema YAML files define a minimum number of tests, including `not_null`, `unique`, and at least one business logic test (e.g. `accepted_values`, `relationships`) |
| **Documentation** | Models and columns have `description:` fields in schema YAML |
| **Write-up** | A `WRITEUP.md` exists with bullet point insights backed by model output |

Results are posted as a step summary and, on pull requests, as a single PR comment that updates on each push (no comment spam).

---

## Setting up the action

Add a workflow file to the student's dbt repo at `.github/workflows/grade.yml`:

```yaml
name: Grade Assignment

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read
  pull-requests: write   # required to post/update the PR comment

jobs:
  grade:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: your-org/dbt-assignment-grader@main
        with:
          level: "1"
          project-path: "."            # path to the dbt project within the repo
          fail-on-incomplete: "false"  # set to "true" to block merges until all checks pass
```

> **Fork PRs**: The default `GITHUB_TOKEN` on fork pull requests has read-only permissions and cannot post comments. To grade fork PRs with comments, use [`pull_request_target`](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#pull_request_target) instead of `pull_request` — but review the [security implications](https://securitylab.github.com/research/github-actions-preventing-pwn-requests/) before doing so.

### Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `level` | `"1"` | Rubric to grade against — integer or slug (e.g. `"level_01"`) |
| `project-path` | `"."` | Relative path from the repo root to the dbt project directory |
| `fail-on-incomplete` | `"true"` | Exit with code 1 if any checks fail — set to `"false"` for feedback-only runs |

### Outputs

| Output | Description |
|--------|-------------|
| `passed` | `"true"` if all checks passed, `"false"` otherwise |
| `passed-count` | Number of checks that passed |
| `total-count` | Total number of checks |
| `level-id` | Numeric rubric id from the level YAML |
| `failed-objectives` | Comma-separated IDs of failed checks |

---

## What the student needs in their repo

For the default rubric (`level_01`), the student's dbt project should include:

- **A mart model** — a `.sql` file named `fct_something.sql` or `dim_something.sql` inside `models/`
- **`ref()` usage** — mart SQL uses `{{ ref('...') }}` for upstream models, not raw `schema.table` names after `FROM` / `JOIN`
- **A schema YAML** — with `not_null`, `unique`, 3–4 tests total including at least one business logic test (e.g. `accepted_values`, `relationships`)
- **Descriptions** — `description:` fields on at least one model and two columns in the schema YAML
- **`WRITEUP.md`** — at least 2 bullet points with insights from the model output and next steps

---

## Customizing the rubric

Rubrics are defined in `grader/levels/level_01.yml`. Each objective specifies a check type and its parameters:

```yaml
id: 1
title: "Analytics Assignment"

objectives:
  - id: has_mart_model
    label: "At least one fct_* or dim_* model exists"
    hint: "Create models/marts/fct_something.sql"
    check:
      type: has_mart_model

  - id: has_key_tests
    label: "Key column has not_null and unique tests"
    hint: "Add both tests to your primary key column in a schema YAML file"
    check:
      type: has_tests
      min: 2
      required_types: ["not_null", "unique"]

  - id: has_writeup
    label: "WRITEUP.md with at least 2 insights"
    hint: "Create WRITEUP.md with bullet points backed by your model output"
    check:
      type: has_writeup
      filename: WRITEUP.md
      min_bullet_points: 2
```

To create a new assignment, add a `level_02.yml` and pass `level: 2` in the workflow.

---

## License

MIT
