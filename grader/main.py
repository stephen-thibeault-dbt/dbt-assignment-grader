"""GitHub Action dbt assignment grader — entry point."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

import yaml

from grader.checks import LevelSpec, run_check

LEVELS_DIR = Path(__file__).parent / "levels"

# Marker embedded in PR comments so we can find and update the existing one
# instead of posting a new comment on every push.
_COMMENT_MARKER = "<!-- dbt-assignment-grader -->"


# ─── Level loading ────────────────────────────────────────────────────────────

def load_level(level_input: str) -> LevelSpec:
    if level_input.startswith("level_"):
        path = LEVELS_DIR / f"{level_input}.yml"
    else:
        path = LEVELS_DIR / f"level_{int(level_input):02d}.yml"
    if not path.exists():
        available = ", ".join(p.stem for p in sorted(LEVELS_DIR.glob("level_*.yml")))
        raise ValueError(f"Level {level_input!r} not found. Available: {available}")
    return LevelSpec(**yaml.safe_load(path.read_text()))


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> int:
    level_input = os.environ.get("GRADER_LEVEL", "1").strip()
    project_path_input = os.environ.get("GRADER_PROJECT_PATH", ".").strip()
    github_token = os.environ.get("GRADER_GITHUB_TOKEN", "").strip() or None
    fail_on_incomplete = os.environ.get("GRADER_FAIL_ON_INCOMPLETE", "true").strip().lower() == "true"

    try:
        spec = load_level(level_input)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    workspace = Path(os.environ.get("GITHUB_WORKSPACE", "/github/workspace"))
    project_dir = Path(project_path_input)
    if not project_dir.is_absolute():
        project_dir = workspace / project_dir
    project_dir = project_dir.resolve()

    if not project_dir.exists():
        print(f"ERROR: Project path not found: {project_dir}", file=sys.stderr)
        return 2

    print(f"[grader] {spec.title} (level {spec.id})", flush=True)
    print(f"[grader] Checking: {project_dir}", flush=True)

    results = [(obj, run_check(obj, project_dir)) for obj in spec.objectives]
    passed = sum(1 for _, r in results if r.passed)
    total = len(results)

    _write_summary(spec, results, passed, total)
    _write_outputs(spec, results, passed, total)

    if github_token and os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        _post_pr_comment(spec, results, passed, total, github_token)

    print(f"[grader] {passed}/{total} passed.", flush=True)
    if passed == total:
        return 0
    return 1 if fail_on_incomplete else 0


# ─── Reporting ────────────────────────────────────────────────────────────────

def _build_markdown(spec: LevelSpec, results, passed: int, total: int) -> str:
    icon = "✅" if passed == total else "❌"
    lines = [
        f"## {icon} Assignment Grader — {spec.title}",
        "",
        f"**{passed} / {total} checks passed**",
        "",
        "| # | Check | Status | Notes |",
        "|---|-------|--------|-------|",
    ]
    for i, (obj, r) in enumerate(results, 1):
        status = "✅ Pass" if r.passed else "❌ Fail"
        notes = (r.reason or "—").replace("|", "\\|")
        lines.append(f"| {i} | {obj.label} | {status} | {notes} |")
    lines += [
        "",
        f"**{'All checks passed!' if passed == total else f'{passed} of {total} checks passed.'}**",
    ]
    return "\n".join(lines)


def _write_summary(spec, results, passed, total) -> None:
    md = _build_markdown(spec, results, passed, total)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(md + "\n")
    else:
        print(md)


def _write_outputs(spec, results, passed, total) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    failed_ids = ",".join(obj.id for obj, r in results if not r.passed)
    with open(output_path, "a") as f:
        f.write("\n".join([
            f"passed={'true' if passed == total else 'false'}",
            f"passed-count={passed}",
            f"total-count={total}",
            f"level-id={spec.id}",
            f"failed-objectives={failed_ids}",
        ]) + "\n")


# ─── PR comment (sticky: update-or-create) ───────────────────────────────────

def _post_pr_comment(spec, results, passed, total, token: str) -> None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = _get_pr_number()
    if not repo or not pr_number:
        print("[grader] Skipping PR comment: could not determine PR number.", flush=True)
        return

    body = _COMMENT_MARKER + "\n" + _build_markdown(spec, results, passed, total)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    existing_id = _find_comment(repo, pr_number, headers)
    if existing_id:
        url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}"
        method = "PATCH"
    else:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        method = "POST"

    req = urllib.request.Request(
        url,
        data=json.dumps({"body": body}).encode(),
        headers=headers,
        method=method,
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print(f"[grader] PR comment {'updated' if existing_id else 'posted'}.", flush=True)
    except Exception as e:
        print(f"[grader] Warning: could not post PR comment: {e}", flush=True)


def _get_pr_number() -> str | None:
    """Read PR number from the event payload — more reliable than parsing GITHUB_REF."""
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        return None
    try:
        event = json.loads(Path(event_path).read_text())
        pr = event.get("pull_request", {}).get("number")
        return str(pr) if pr else None
    except Exception:
        return None


def _find_comment(repo: str, pr_number: str, headers: dict) -> int | None:
    """Return the id of the existing grader comment on this PR, or None."""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100"
    req = urllib.request.Request(url, headers={k: v for k, v in headers.items() if k != "Content-Type"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            for comment in json.loads(resp.read()):
                if _COMMENT_MARKER in comment.get("body", ""):
                    return comment["id"]
    except Exception:
        pass
    return None


if __name__ == "__main__":
    sys.exit(main())
