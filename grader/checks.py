"""Check type definitions and static file-based implementations."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict


# ─── Check type models ────────────────────────────────────────────────────────

class HasMartModel(BaseModel):
    type: Literal["has_mart_model"] = "has_mart_model"
    prefix: str = ""  # e.g. "fct_" — if empty, accepts fct_* or dim_*

class HasTests(BaseModel):
    type: Literal["has_tests"] = "has_tests"
    min: int = 2
    max: int = 0               # 0 = no upper limit
    required_types: list[str] = []
    min_custom: int = 0        # minimum non-built-in tests

class HasDocumentation(BaseModel):
    type: Literal["has_documentation"] = "has_documentation"
    min_described_models: int = 1
    min_described_columns: int = 0

class HasWriteup(BaseModel):
    type: Literal["has_writeup"] = "has_writeup"
    filename: str = "WRITEUP.md"
    min_bullet_points: int = 1

class HasRefCall(BaseModel):
    type: Literal["has_ref_call"] = "has_ref_call"
    filename: str   # supports glob patterns, e.g. "models/**/*.sql"
    target_model: str = ""  # if empty, checks for any ref() call

class FileContains(BaseModel):
    type: Literal["file_contains"] = "file_contains"
    filename: str
    pattern: str

class NoHardcodedRefs(BaseModel):
    type: Literal["no_hardcoded_refs"] = "no_hardcoded_refs"
    filename: str   # supports glob patterns, e.g. "models/**/*.sql"

class HasTest(BaseModel):
    type: Literal["has_test"] = "has_test"
    model_name: str
    column_name: str
    test_type: str

class HasFreshnessConfig(BaseModel):
    type: Literal["has_freshness_config"] = "has_freshness_config"
    source_name: str
    table_name: str

class DbtParses(BaseModel):
    type: Literal["dbt_parses"] = "dbt_parses"

class DbtFusionParses(BaseModel):
    type: Literal["dbt_fusion_parses"] = "dbt_fusion_parses"


ObjectiveCheck = Union[
    HasMartModel, HasTests, HasDocumentation, HasWriteup,
    HasRefCall, FileContains, NoHardcodedRefs, HasTest, HasFreshnessConfig,
    DbtParses, DbtFusionParses,
]


# ─── Level schema ─────────────────────────────────────────────────────────────

class ObjectiveDefinition(BaseModel):
    id: str
    label: str
    hint: str = ""
    check: ObjectiveCheck

class LevelSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    title: str
    objectives: list[ObjectiveDefinition]


# ─── Result ───────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    passed: bool
    reason: str | None = None


def _ok() -> CheckResult:
    return CheckResult(True)

def _fail(msg: str) -> CheckResult:
    return CheckResult(False, msg)


# ─── Check runner ─────────────────────────────────────────────────────────────

def run_check(obj: ObjectiveDefinition, project_dir: Path) -> CheckResult:
    c = obj.check

    if c.type == "has_mart_model":
        models_dir = project_dir / "models"
        if not models_dir.exists():
            return _fail("No models/ directory found in the project.")
        patterns = [f"**/{c.prefix}*.sql"] if c.prefix else ["**/fct_*.sql", "**/dim_*.sql"]
        for pattern in patterns:
            if list(models_dir.glob(pattern)):
                return _ok()
        label = f"{c.prefix}*" if c.prefix else "fct_* or dim_*"
        return _fail(f"No {label} model found under models/.")

    if c.type == "has_tests":
        tests = _collect_tests(project_dir)
        total = len(tests)
        if total < c.min:
            return _fail(f"Found {total} test(s), need at least {c.min}.")
        if c.max and total > c.max:
            return _fail(f"Found {total} test(s), expected at most {c.max}.")
        found_types = {t.lower() for t in tests}
        missing = [t for t in c.required_types if t.lower() not in found_types]
        if missing:
            return _fail(f"Missing required test type(s): {', '.join(missing)}.")
        if c.min_custom:
            # Only not_null and unique are structural — everything else counts as business logic
            _STRUCTURAL = {"not_null", "unique"}
            custom = [t for t in tests if t.lower() not in _STRUCTURAL]
            if len(custom) < c.min_custom:
                return _fail(
                    f"Need at least {c.min_custom} business logic test(s) "
                    f"(e.g. accepted_values, relationships), found {len(custom)}."
                )
        return _ok()

    if c.type == "has_documentation":
        described_models, described_cols = _collect_documentation(project_dir)
        if described_models < c.min_described_models:
            return _fail(
                f"Found {described_models} model(s) with a description, "
                f"need at least {c.min_described_models}."
            )
        if described_cols < c.min_described_columns:
            return _fail(
                f"Found {described_cols} column(s) with a description, "
                f"need at least {c.min_described_columns}."
            )
        return _ok()

    if c.type == "has_writeup":
        path = project_dir / c.filename
        if not path.exists():
            return _fail(f"'{c.filename}' not found. Create it with bullet point insights.")
        content = path.read_text()
        if not content.strip():
            return _fail(f"'{c.filename}' is empty.")
        bullets = sum(1 for line in content.splitlines() if re.match(r"^\s*[-*]\s+\S", line))
        if bullets < c.min_bullet_points:
            return _fail(f"Found {bullets} bullet point(s), need at least {c.min_bullet_points}.")
        return _ok()

    if c.type == "has_ref_call":
        files = _resolve_files(c.filename, project_dir)
        if not files:
            return _fail(f"No files found matching '{c.filename}'.")
        if c.target_model:
            pattern = rf"\{{\{{\s*ref\s*\(\s*['\"]{ re.escape(c.target_model) }['\"]\s*\)\s*\}}\}}"
            label = f"ref('{c.target_model}')"
        else:
            pattern = r"\{\{\s*ref\s*\("
            label = "ref()"
        for path in files:
            if re.search(pattern, _strip_comments(path.read_text())):
                return _ok()
        return _fail(f"No {label} call found in {c.filename}.")

    if c.type == "file_contains":
        if not (project_dir / c.filename).exists():
            return _fail(f"'{c.filename}' not found.")
        content = _read(c.filename, project_dir)
        if not content.strip():
            return _fail(f"'{c.filename}' is empty.")
        try:
            return _ok() if re.search(c.pattern, content, re.IGNORECASE | re.DOTALL) else _fail(
                f"Required content not found in {c.filename}."
            )
        except re.error:
            return _fail(f"Required content not found in {c.filename}.")

    if c.type == "no_hardcoded_refs":
        files = _resolve_files(c.filename, project_dir)
        if not files:
            return _fail(f"No files found matching '{c.filename}'.")
        for path in files:
            raw = path.read_text()
            if re.search(r"\{\{[^}]*static_analysis\s*=\s*['\"]unsafe['\"]", raw):
                continue
            uncommented = _strip_comments(raw)
            if not re.search(r"\{\{\s*(ref|source)\s*\(", uncommented):
                return _fail(f"No ref() or source() calls found in {path.name} — use {{{{ ref('model') }}}} instead of direct table names.")
            stripped = re.sub(r"\{\{[^}]+\}\}", "", uncommented)
            m = re.search(r"\b(?:from|join)\s+(\w+\.\w+)", stripped, re.IGNORECASE)
            if m:
                return _fail(f"Hardcoded table reference '{m.group(1)}' in {path.name} — replace with ref().")
        return _ok()

    if c.type == "has_test":
        for path in project_dir.rglob("*.yml"):
            if _EXCLUDED_DIRS & set(path.parts) or any(p.startswith(".") for p in path.parts):
                continue
            text = path.read_text()
            if c.model_name not in text:
                continue
            if re.search(
                rf"name:\s*{re.escape(c.column_name)}[\s\S]*?tests:[\s\S]*?-\s*{re.escape(c.test_type)}",
                text,
            ):
                return _ok()
        return _fail(f"Test '{c.test_type}' not found on column '{c.column_name}' for model '{c.model_name}'.")

    if c.type == "has_freshness_config":
        for path in project_dir.rglob("*.yml"):
            if _EXCLUDED_DIRS & set(path.parts) or any(p.startswith(".") for p in path.parts):
                continue
            text = path.read_text()
            if f"name: {c.source_name}" in text and f"name: {c.table_name}" in text and "freshness" in text:
                missing = [k for k in ("warn_after", "error_after") if k not in text]
                return _ok() if not missing else _fail(f"Freshness block missing: {', '.join(missing)}.")
        return _fail(f"No freshness config found for source '{c.source_name}.{c.table_name}'.")

    if c.type in ("dbt_parses", "dbt_fusion_parses"):
        dbt_project_file = project_dir / "dbt_project.yml"
        if not dbt_project_file.exists():
            return _fail("dbt_project.yml not found.")
        try:
            dbt_project = yaml.safe_load(dbt_project_file.read_text()) or {}
        except Exception as e:
            return _fail(f"Could not read dbt_project.yml: {e}")
        profile_name = dbt_project.get("profile", "default")
        fake_profiles = {
            profile_name: {
                "target": "dev",
                "outputs": {
                    "dev": {
                        "type": "bigquery",
                        "method": "oauth",
                        "project": "fake-project",
                        "dataset": "fake_dataset",
                        "threads": 1,
                    }
                },
            }
        }
        if c.type == "dbt_parses":
            # Use the dbt installed alongside this Python to avoid picking up Fusion
            dbt_bin = str(Path(sys.executable).parent / "dbt")
            label = "dbt parse"
        else:
            dbt_bin = os.environ.get("FUSION_DBT_BIN", "")
            if not dbt_bin or not Path(dbt_bin).exists():
                return _fail("Fusion binary not found — ensure the 'Install dbt Fusion' action step ran first.")
            label = "dbt Fusion parse"
        with tempfile.TemporaryDirectory() as tmp:
            profiles_path = Path(tmp) / "profiles.yml"
            profiles_path.write_text(yaml.dump(fake_profiles))
            result = subprocess.run(
                [dbt_bin, "parse", "--profiles-dir", tmp, "--project-dir", str(project_dir), "--no-use-colors"],
                capture_output=True,
                text=True,
            )
        if result.returncode == 0:
            return _ok()
        output = (result.stdout + result.stderr).strip()
        error_line = next((ln.strip() for ln in output.splitlines() if ln.strip()), output[:200])
        return _fail(f"{label} failed: {error_line}")

    return _fail(f"Unknown check type: {c.type}")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _read(filename: str, project_dir: Path) -> str:
    p = project_dir / filename
    return p.read_text() if p.exists() else ""

def _resolve_files(filename: str, project_dir: Path) -> list[Path]:
    """Return matching files — supports glob patterns or exact paths."""
    if "*" in filename:
        return [p for p in project_dir.glob(filename) if p.is_file()]
    p = project_dir / filename
    return [p] if p.exists() else []

def _strip_comments(sql: str) -> str:
    return re.sub(r"--.*$", "", sql, flags=re.MULTILINE)

_EXCLUDED_DIRS = {"target", "dbt_packages"}

def _schema_yamls(project_dir: Path):
    for path in project_dir.rglob("*.yml"):
        if not path.is_file():
            continue
        if _EXCLUDED_DIRS & set(path.parts) or any(p.startswith(".") for p in path.parts):
            continue
        try:
            yield yaml.safe_load(path.read_text()) or {}
        except Exception:
            continue

def _collect_tests(project_dir: Path) -> list[str]:
    tests: list[str] = []
    for data in _schema_yamls(project_dir):
        for model in data.get("models", []):
            if not isinstance(model, dict):
                continue
            for col in model.get("columns", []):
                if not isinstance(col, dict):
                    continue
                for t in col.get("tests", []) + col.get("data_tests", []):
                    tests.append(t if isinstance(t, str) else next(iter(t)))
            for t in model.get("tests", []) + model.get("data_tests", []):
                tests.append(t if isinstance(t, str) else next(iter(t)))
    return tests

def _collect_documentation(project_dir: Path) -> tuple[int, int]:
    models_with_desc = cols_with_desc = 0
    for data in _schema_yamls(project_dir):
        for model in data.get("models", []):
            if not isinstance(model, dict):
                continue
            if str(model.get("description", "")).strip():
                models_with_desc += 1
            for col in model.get("columns", []):
                if str(col.get("description", "")).strip():
                    cols_with_desc += 1
    return models_with_desc, cols_with_desc
