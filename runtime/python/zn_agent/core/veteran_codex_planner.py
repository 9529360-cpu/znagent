from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Mapping

from .veteran_engineering import VeteranSidecarError, discover_veteran_codex_worker

_MAX_INPUT_CHARS = 512_000
_MAX_TASKS = 16
_MAX_PATHS_PER_TASK = 64
_RISKS = {"low", "medium", "high", "critical"}

_TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "contract",
        "owner",
        "dependencies",
        "writeSet",
        "protectedPaths",
        "risk",
        "validationCapability",
        "worker",
        "notes",
    ],
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 64},
        "contract": {"type": "string", "minLength": 1, "maxLength": 4000},
        "owner": {"type": "string", "minLength": 1, "maxLength": 400},
        "dependencies": {
            "type": "array",
            "maxItems": 64,
            "items": {"type": "string", "minLength": 1, "maxLength": 64},
        },
        "writeSet": {
            "type": "array",
            "maxItems": _MAX_PATHS_PER_TASK,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "protectedPaths": {
            "type": "array",
            "maxItems": _MAX_PATHS_PER_TASK,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "risk": {"type": "string", "enum": sorted(_RISKS)},
        "validationCapability": {
            "type": ["string", "null"],
            "maxLength": 200,
        },
        "worker": {"type": ["string", "null"], "maxLength": 120},
        "notes": {"type": ["string", "null"], "maxLength": 2000},
    },
}

_PLANNER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tasks"],
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": 1,
            "maxItems": _MAX_TASKS,
            "items": _TASK_SCHEMA,
        }
    },
}


def _bounded_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _relative_repo_path(value: Any) -> str:
    rendered = str(value or "").strip().replace("\\", "/")
    if not rendered or rendered in {".", "/"}:
        raise ValueError("planner write paths must name a bounded repository-relative path")
    candidate = Path(rendered)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError(f"planner path is not repository-relative: {rendered}")
    if ":" in candidate.parts[0]:
        raise ValueError(f"planner path must not contain a drive prefix: {rendered}")
    return candidate.as_posix()


def validate_veteran_planner_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("protocol") != "veteran-planner-v1":
        raise ValueError("unsupported Veteran planner protocol")
    project = payload.get("project")
    mission = payload.get("mission")
    if not isinstance(project, dict) or not isinstance(mission, dict):
        raise ValueError("Veteran planner payload is missing project or mission")
    goal = _bounded_text(mission.get("goal"), 6000)
    done = _bounded_text(mission.get("doneDefinition"), 6000)
    if not goal or not done:
        raise ValueError("Veteran planner goal and doneDefinition are required")
    return {
        "project": {
            "id": _bounded_text(project.get("id"), 160),
            "repoPath": _bounded_text(project.get("repoPath"), 2000),
            "sourceIdentity": project.get("sourceIdentity"),
            "sourceAuthority": project.get("sourceAuthority"),
        },
        "mission": {
            "goal": goal,
            "doneDefinition": done,
            "nonGoals": [
                _bounded_text(item, 1000)
                for item in (mission.get("nonGoals") or [])[:32]
                if _bounded_text(item, 1000)
            ],
            "riskEnvelope": _bounded_text(mission.get("riskEnvelope"), 32) or "medium",
        },
        "projectAwareness": payload.get("projectAwareness"),
        "projectExperience": (payload.get("projectExperience") or [])[:8],
        "limits": {"maxTasks": _MAX_TASKS},
    }


def build_codex_planner_prompt(payload: Mapping[str, Any]) -> str:
    safe = validate_veteran_planner_input(payload)
    return (
        "You are the read-only planning phase of a bounded Veteran Engineer Mission. "
        "Inspect the current Git repository and return only the JSON object required by "
        "the supplied output schema. Plan the smallest complete dependency-aware task DAG. "
        "Each task must declare observable contract, authoritative owner, predicted writeSet, "
        "dependencies, and risk. writeSet entries must be repository-relative concrete files "
        "or bounded directories; never use '.', absolute paths, '..', broad wildcards, release, "
        "deployment, credentials, or production actions. Do not modify files, Git state, hooks, "
        "configuration, branches, or remotes. Current repository/runtime evidence outranks "
        "project experience. Keep the plan within the mission risk envelope and at most "
        f"{_MAX_TASKS} tasks.\n\nPlanner input:\n"
        + json.dumps(safe, ensure_ascii=False, sort_keys=True)
    )


def validate_codex_task_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"tasks"}:
        raise ValueError("Codex planner output must contain only tasks")
    raw_tasks = value.get("tasks")
    if not isinstance(raw_tasks, list) or not 1 <= len(raw_tasks) <= _MAX_TASKS:
        raise ValueError(f"Codex planner must return 1..{_MAX_TASKS} tasks")

    tasks: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, raw in enumerate(raw_tasks):
        if not isinstance(raw, dict):
            raise ValueError(f"planner task {index} must be an object")
        task_id = _bounded_text(raw.get("id") or f"T{index + 1}", 64)
        if not task_id or task_id in ids:
            raise ValueError("planner task ids must be unique and non-empty")
        ids.add(task_id)
        contract = _bounded_text(raw.get("contract"), 4000)
        owner = _bounded_text(raw.get("owner"), 400)
        if not contract or not owner:
            raise ValueError(f"planner task {task_id} is missing contract or owner")
        risk = _bounded_text(raw.get("risk"), 32).lower()
        if risk not in _RISKS:
            raise ValueError(f"planner task {task_id} has invalid risk: {risk}")
        raw_write_set = raw.get("writeSet")
        if not isinstance(raw_write_set, list) or len(raw_write_set) > _MAX_PATHS_PER_TASK:
            raise ValueError(f"planner task {task_id} has invalid writeSet")
        write_set = list(dict.fromkeys(_relative_repo_path(item) for item in raw_write_set))
        raw_protected = raw.get("protectedPaths") or []
        if not isinstance(raw_protected, list) or len(raw_protected) > _MAX_PATHS_PER_TASK:
            raise ValueError(f"planner task {task_id} has invalid protectedPaths")
        protected = list(dict.fromkeys(_relative_repo_path(item) for item in raw_protected))
        dependencies = [
            _bounded_text(item, 64)
            for item in (raw.get("dependencies") or [])
            if _bounded_text(item, 64)
        ]
        tasks.append(
            {
                "id": task_id,
                "contract": contract,
                "owner": owner,
                "dependencies": list(dict.fromkeys(dependencies)),
                "writeSet": write_set,
                "protectedPaths": protected,
                "risk": risk,
                **(
                    {"validationCapability": _bounded_text(raw.get("validationCapability"), 200)}
                    if _bounded_text(raw.get("validationCapability"), 200)
                    else {}
                ),
                **(
                    {"worker": _bounded_text(raw.get("worker"), 120)}
                    if _bounded_text(raw.get("worker"), 120)
                    else {}
                ),
                **(
                    {"notes": _bounded_text(raw.get("notes"), 2000)}
                    if _bounded_text(raw.get("notes"), 2000)
                    else {}
                ),
            }
        )

    for task in tasks:
        unknown = [dependency for dependency in task["dependencies"] if dependency not in ids]
        if unknown:
            raise ValueError(
                f"planner task {task['id']} depends on unknown task(s): {', '.join(unknown)}"
            )
        if task["id"] in task["dependencies"]:
            raise ValueError(f"planner task {task['id']} may not depend on itself")
    return {"tasks": tasks}


def _git_checked(
    repo: Path,
    args: list[str],
    *,
    timeout_seconds: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, min(float(timeout_seconds), 120.0)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VeteranSidecarError(f"planner Git isolation failed: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-3000:]
        raise VeteranSidecarError(
            f"planner Git isolation command failed ({' '.join(args)}): {detail}"
        )
    return result


@contextmanager
def disposable_planner_clone(
    repo_path: str | os.PathLike[str],
):
    """Yield an independent disposable clone and prove source + clone stay unchanged.

    Windows Codex read-only sandboxing can stall while executing otherwise valid
    shell reads.  ZN therefore gives the planner workspace-write only inside an
    isolated no-hardlink clone.  The clone has no origin remote, and both source
    and clone Git identity are revalidated before the plan can be accepted.
    """

    repo = Path(repo_path).expanduser().resolve(strict=True)
    top = Path(
        _git_checked(repo, ["rev-parse", "--show-toplevel"]).stdout.strip()
    ).resolve(strict=True)
    if top != repo:
        raise VeteranSidecarError(
            "Veteran Codex planner requires the exact Git repository root"
        )
    source_head = _git_checked(repo, ["rev-parse", "HEAD"]).stdout.strip()
    source_status = _git_checked(
        repo,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
    ).stdout
    if source_status:
        raise VeteranSidecarError(
            "Veteran Codex planner requires a clean source checkout"
        )

    with tempfile.TemporaryDirectory(prefix="zn-veteran-planner-clone-") as temp:
        checkout = Path(temp) / "repo"
        try:
            cloned = subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--no-hardlinks",
                    str(repo),
                    str(checkout),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VeteranSidecarError(
                f"planner disposable clone failed: {exc}"
            ) from exc
        if cloned.returncode != 0:
            detail = (cloned.stderr or cloned.stdout or "").strip()[-3000:]
            raise VeteranSidecarError(
                f"planner disposable clone failed: {detail}"
            )

        _git_checked(checkout, ["checkout", "--quiet", "--detach", source_head])
        # A local origin would be a write-back path to the user's repository
        # even with network disabled.  Planning only needs repository truth.
        _git_checked(checkout, ["remote", "remove", "origin"])

        clone_head = _git_checked(checkout, ["rev-parse", "HEAD"]).stdout.strip()
        clone_status = _git_checked(
            checkout,
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        ).stdout
        if clone_head != source_head or clone_status:
            raise VeteranSidecarError(
                "planner disposable clone does not match clean source HEAD"
            )

        mutation_error: VeteranSidecarError | None = None
        try:
            yield checkout
            after_head = _git_checked(checkout, ["rev-parse", "HEAD"]).stdout.strip()
            after_status = _git_checked(
                checkout,
                ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            ).stdout
            if after_head != source_head:
                mutation_error = VeteranSidecarError(
                    "Codex planner changed Git HEAD inside its disposable clone"
                )
            elif after_status:
                mutation_error = VeteranSidecarError(
                    "Codex planner modified files inside its disposable clone"
                )
        finally:
            source_after_head = _git_checked(repo, ["rev-parse", "HEAD"]).stdout.strip()
            source_after_status = _git_checked(
                repo,
                ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            ).stdout
            if source_after_head != source_head or source_after_status != source_status:
                mutation_error = VeteranSidecarError(
                    "Codex planner changed the source repository despite clone isolation"
                )

        if mutation_error is not None:
            raise mutation_error


def _payload_for_planner_repo(
    payload: Mapping[str, Any],
    planner_repo: Path,
) -> dict[str, Any]:
    rewritten = dict(payload)
    project = payload.get("project")
    if isinstance(project, Mapping):
        project_copy = dict(project)
        project_copy["repoPath"] = str(planner_repo)
        project_copy.pop("checkoutRepoPath", None)
        rewritten["project"] = project_copy
    return rewritten


def run_codex_planner(
    payload: Mapping[str, Any],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = 170.0,
) -> dict[str, Any]:
    effective_env = dict(os.environ if env is None else env)
    worker = discover_veteran_codex_worker(effective_env)
    if worker is None:
        raise VeteranSidecarError("Codex planner worker is unavailable")

    source_repo = Path(cwd or os.getcwd()).expanduser().resolve(strict=True)
    windows_workspace_fallback = bool(worker.windows_sandbox)
    planner_context = (
        disposable_planner_clone(source_repo)
        if windows_workspace_fallback
        else nullcontext(source_repo)
    )
    with planner_context as planner_repo:
        planner_payload = (
            _payload_for_planner_repo(payload, planner_repo)
            if windows_workspace_fallback
            else dict(payload)
        )
        prompt = build_codex_planner_prompt(planner_payload)
        with tempfile.TemporaryDirectory(prefix="zn-veteran-planner-output-") as tmp:
            root = Path(tmp)
            schema_path = root / "schema.json"
            result_path = root / "result.json"
            schema_path.write_text(
                json.dumps(_PLANNER_SCHEMA, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            args = ["exec"]
            if worker.windows_sandbox:
                args.extend(["-c", f'windows.sandbox="{worker.windows_sandbox}"'])
            args.extend(
                [
                    "--sandbox",
                    "workspace-write" if windows_workspace_fallback else "read-only",
                    "--ephemeral",
                    "--color",
                    "never",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(result_path),
                    "-C",
                    str(planner_repo),
                    "-",
                ]
            )
            run_env = dict(effective_env)
            if worker.codex_home is not None:
                run_env["CODEX_HOME"] = str(worker.codex_home)
            try:
                completed = subprocess.run(
                    [str(worker.command), *args],
                    input=prompt,
                    cwd=str(planner_repo),
                    env=run_env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=max(5.0, min(float(timeout_seconds), 300.0)),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise VeteranSidecarError(
                    f"Codex planner timed out after {float(timeout_seconds):.1f} seconds"
                ) from exc
            if completed.returncode != 0:
                stderr = (completed.stderr or "")[-4000:]
                raise VeteranSidecarError(
                    f"Codex planner failed with exit {completed.returncode}: {stderr}"
                )
            try:
                parsed = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise VeteranSidecarError(
                    "Codex planner returned no valid schema result"
                ) from exc
    return validate_codex_task_plan(parsed)


def main() -> int:
    raw = sys.stdin.read(_MAX_INPUT_CHARS + 1)
    if len(raw) > _MAX_INPUT_CHARS:
        print("Veteran planner input exceeded the bounded limit", file=sys.stderr)
        return 2
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("planner input must be a JSON object")
        result = run_codex_planner(payload)
    except (ValueError, VeteranSidecarError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
