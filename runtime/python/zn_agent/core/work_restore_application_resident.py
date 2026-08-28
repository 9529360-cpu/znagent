from __future__ import annotations

"""Explicitly approved restore of retained Work bytes into a missing file path.

The first restore application slice is intentionally narrow: ZN may recreate an
exact retained file only when fresh reality proves the target is still missing.
It never overwrites a changed/current file. Approval is a separate durable step,
namespace commit is no-replace, and restart reconciliation observes reality but
never resumes a pending mutation automatically.
"""

import hashlib
import json
import os
import stat
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from .file_identity import DEFAULT_MAX_HASH_BYTES, observe_file_identity
from .models import utc_now
from .staged_bytes_restore import (
    commit_staged_bytes_to_missing_target_windows,
    restore_bytes_to_missing_target_windows,
    restore_staging_path,
)
from .work_restore_point_inspection_resident import (
    WorkRestorePointInspectionResidentRuntime,
)
from .work_restore_point_resident import _TABLE as _RESTORE_TABLE


_APPLICATION_TABLE = "work_restore_applications"
_TRANSIENT_STATUSES = {"applying", "stage_ready", "commit_started"}
_APPROVABLE_STATUSES = {"approval_required", "recovery_required"}
_FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x00000400)


class WorkRestoreApplicationResidentRuntime(WorkRestorePointInspectionResidentRuntime):
    """Apply one exact retained file only with explicit user control authority."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._init_restore_application_schema()
        self.reconcile_restore_applications()

    def _init_restore_application_schema(self) -> None:
        with closing(self._restore_connect()) as conn:
            conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {_APPLICATION_TABLE}(
                    application_id TEXT PRIMARY KEY,
                    restore_point_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    staging_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_identity_json TEXT NOT NULL,
                    parent_identity_json TEXT NOT NULL,
                    stage_identity_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(restore_point_id) REFERENCES {_RESTORE_TABLE}(restore_point_id)
                );
                CREATE INDEX IF NOT EXISTS idx_work_restore_application_thread
                    ON {_APPLICATION_TABLE}(thread_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_work_restore_application_status
                    ON {_APPLICATION_TABLE}(status, updated_at ASC);
                """
            )
            conn.commit()

    @staticmethod
    def _stable_missing(identity: dict[str, Any]) -> bool:
        return bool(
            identity.get("observable") is True
            and identity.get("stable") is True
            and identity.get("exists") is False
        )

    @staticmethod
    def _content_matches(
        identity: dict[str, Any],
        *,
        size_bytes: int,
        content_sha256: str,
    ) -> bool:
        return bool(
            identity.get("observable") is True
            and identity.get("stable") is True
            and identity.get("exists") is True
            and str(identity.get("type") or "") == "file"
            and identity.get("digest_complete") is True
            and identity.get("size_bytes") == int(size_bytes)
            and str(identity.get("content_sha256") or "") == content_sha256
        )

    @staticmethod
    def _same_parent_identity(
        expected: dict[str, Any], current: dict[str, Any]
    ) -> bool:
        return bool(
            expected.get("observable") is True
            and expected.get("stable") is True
            and expected.get("exists") is True
            and expected.get("type") == "directory"
            and current.get("observable") is True
            and current.get("stable") is True
            and current.get("exists") is True
            and current.get("type") == "directory"
            and expected.get("path") == current.get("path")
            and expected.get("device") == current.get("device")
            and expected.get("inode") == current.get("inode")
        )

    @staticmethod
    def _observe_parent(target: Path) -> dict[str, Any]:
        parent = target.parent
        identity = observe_file_identity(parent, max_hash_bytes=0)
        try:
            info = parent.lstat()
        except OSError:
            return identity
        attributes = int(getattr(info, "st_file_attributes", 0) or 0)
        identity = dict(identity)
        identity["reparse_point"] = bool(
            stat.S_ISLNK(int(info.st_mode)) or attributes & _FILE_ATTRIBUTE_REPARSE_POINT
        )
        return identity

    @classmethod
    def _safe_parent(cls, identity: dict[str, Any]) -> bool:
        return bool(
            identity.get("observable") is True
            and identity.get("stable") is True
            and identity.get("exists") is True
            and identity.get("type") == "directory"
            and identity.get("reparse_point") is False
        )

    def _owned_restore_point(
        self,
        thread_id: str,
        restore_point_id: str,
    ) -> tuple[Any, dict[str, Any], bytes]:
        normalized_thread = str(thread_id or "").strip()
        normalized_point = str(restore_point_id or "").strip()
        if not normalized_thread or not normalized_point:
            raise ValueError("Work restore requires thread_id and restore_point_id")

        with closing(self._restore_connect()) as conn:
            row = conn.execute(
                f"SELECT * FROM {_RESTORE_TABLE} WHERE restore_point_id=?",
                (normalized_point,),
            ).fetchone()
            if row is None or str(row["thread_id"]) != normalized_thread:
                raise ValueError("unknown Work restore point for thread")
            run = conn.execute(
                "SELECT event_id,thread_id,message_id,task FROM work_runs WHERE event_id=?",
                (str(row["event_id"]),),
            ).fetchone()
            if run is None or (
                str(run["event_id"]) != str(row["event_id"])
                or str(run["thread_id"]) != normalized_thread
                or str(run["message_id"]) != str(row["message_id"])
            ):
                raise RuntimeError("durable Work restore point conflicts with its Work ownership")

        event = self.store.get_event(str(row["event_id"]))
        payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
        if (
            event is None
            or event.task != str(run["task"])
            or str(payload.get("work_thread_id") or "").strip() != normalized_thread
            or str(payload.get("work_message_id") or "").strip() != str(row["message_id"])
        ):
            raise RuntimeError(
                "durable Work restore point conflicts with its resident event ownership"
            )

        try:
            expected = json.loads(row["pre_identity_json"] or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("durable Work restore identity is malformed") from exc
        if not self._capturable_identity(expected):
            raise RuntimeError("durable Work restore identity is not exact")
        if str(expected.get("path") or "") != str(row["target_path"]):
            raise RuntimeError("durable Work restore target conflicts with retained identity")

        content = bytes(row["content"])
        size_bytes = int(row["size_bytes"])
        content_sha256 = str(row["content_sha256"])
        if (
            len(content) != size_bytes
            or hashlib.sha256(content).hexdigest() != content_sha256
            or expected.get("size_bytes") != size_bytes
            or str(expected.get("content_sha256") or "") != content_sha256
        ):
            raise RuntimeError("durable Work restore bytes failed integrity verification")
        return row, expected, content

    def _application_row(self, application_id: str):
        normalized = str(application_id or "").strip()
        if not normalized:
            raise ValueError("Work restore application requires application_id")
        with closing(self._restore_connect()) as conn:
            return conn.execute(
                f"SELECT * FROM {_APPLICATION_TABLE} WHERE application_id=?",
                (normalized,),
            ).fetchone()

    @staticmethod
    def _application_public(row) -> dict[str, Any]:
        status = str(row["status"])
        return {
            "application_id": str(row["application_id"]),
            "restore_point_id": str(row["restore_point_id"]),
            "thread_id": str(row["thread_id"]),
            "event_id": str(row["event_id"]),
            "target_path": str(row["target_path"]),
            "status": status,
            "requires_user_approval": status in _APPROVABLE_STATUSES,
            "fresh_revalidation_required": status in _APPROVABLE_STATUSES,
            "automatic_authority": False,
            "error": str(row["error"] or "") or None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "completed_at": str(row["completed_at"] or "") or None,
        }

    def _set_application(
        self,
        application_id: str,
        *,
        status: str,
        current_identity: dict[str, Any] | None = None,
        stage_identity: dict[str, Any] | None = None,
        error: str | None = None,
        completed: bool = False,
    ) -> None:
        now = utc_now()
        with closing(self._restore_connect()) as conn:
            row = conn.execute(
                f"SELECT current_identity_json,stage_identity_json FROM {_APPLICATION_TABLE} "
                "WHERE application_id=?",
                (application_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown Work restore application")
            current_json = (
                json.dumps(current_identity, ensure_ascii=False, separators=(",", ":"))
                if isinstance(current_identity, dict)
                else str(row["current_identity_json"])
            )
            stage_json = (
                json.dumps(stage_identity, ensure_ascii=False, separators=(",", ":"))
                if isinstance(stage_identity, dict)
                else row["stage_identity_json"]
            )
            conn.execute(
                f"""
                UPDATE {_APPLICATION_TABLE}
                SET status=?,current_identity_json=?,stage_identity_json=?,error=?,
                    updated_at=?,completed_at=?
                WHERE application_id=?
                """,
                (
                    str(status),
                    current_json,
                    stage_json,
                    str(error or "")[:500] or None,
                    now,
                    now if completed else None,
                    application_id,
                ),
            )
            conn.commit()

    def inspect_work_restore_application(self, application_id: str) -> dict[str, Any]:
        row = self._application_row(application_id)
        if row is None:
            raise ValueError("unknown Work restore application")
        return self._application_public(row)

    def prepare_missing_work_restore(
        self,
        thread_id: str,
        restore_point_id: str,
    ) -> dict[str, Any]:
        """Create an approval request only while the exact target is missing."""

        if os.name != "nt":
            raise RuntimeError("missing-file Work restore application currently requires Windows")
        row, _, _ = self._owned_restore_point(thread_id, restore_point_id)
        target = Path(str(row["target_path"]))
        current = observe_file_identity(target, max_hash_bytes=DEFAULT_MAX_HASH_BYTES)
        parent = self._observe_parent(target)
        if not self._stable_missing(current):
            raise RuntimeError(
                "missing-file Work restore requires fresh stable evidence that target is absent"
            )
        if not self._safe_parent(parent):
            raise RuntimeError(
                "missing-file Work restore requires an existing non-reparse parent directory"
            )

        application_id = f"restore-app-{uuid.uuid4().hex[:20]}"
        staging = restore_staging_path(target, application_id)
        now = utc_now()
        with closing(self._restore_connect()) as conn:
            conn.execute(
                f"""
                INSERT INTO {_APPLICATION_TABLE}(
                    application_id,restore_point_id,thread_id,event_id,message_id,
                    target_path,staging_path,status,current_identity_json,parent_identity_json,
                    stage_identity_json,error,created_at,updated_at,completed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    application_id,
                    str(row["restore_point_id"]),
                    str(row["thread_id"]),
                    str(row["event_id"]),
                    str(row["message_id"]),
                    str(target),
                    str(staging),
                    "approval_required",
                    json.dumps(current, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(parent, ensure_ascii=False, separators=(",", ":")),
                    None,
                    None,
                    now,
                    now,
                    None,
                ),
            )
            conn.commit()
        return self.inspect_work_restore_application(application_id)

    def _verify_restored_target(
        self,
        target: Path,
        *,
        size_bytes: int,
        content_sha256: str,
    ) -> dict[str, Any]:
        identity = observe_file_identity(target, max_hash_bytes=DEFAULT_MAX_HASH_BYTES)
        if not self._content_matches(
            identity,
            size_bytes=size_bytes,
            content_sha256=content_sha256,
        ):
            raise RuntimeError("restored target does not match retained exact bytes")
        return identity

    def _stage_matches(
        self,
        staging: Path,
        *,
        size_bytes: int,
        content_sha256: str,
    ) -> tuple[bool, dict[str, Any]]:
        identity = observe_file_identity(staging, max_hash_bytes=DEFAULT_MAX_HASH_BYTES)
        return (
            self._content_matches(
                identity,
                size_bytes=size_bytes,
                content_sha256=content_sha256,
            ),
            identity,
        )

    def _discard_exact_stage(
        self,
        staging: Path,
        *,
        size_bytes: int,
        content_sha256: str,
    ) -> bool:
        if not os.path.lexists(str(staging)):
            return True
        stage_ok, _ = self._stage_matches(
            staging,
            size_bytes=size_bytes,
            content_sha256=content_sha256,
        )
        if not stage_ok:
            return False
        try:
            staging.unlink()
        except OSError:
            return False
        return True

    def _reconcile_application(self, application_id: str) -> dict[str, Any]:
        app = self._application_row(application_id)
        if app is None:
            raise ValueError("unknown Work restore application")
        try:
            point, _, _ = self._owned_restore_point(
                str(app["thread_id"]), str(app["restore_point_id"])
            )
        except Exception as exc:
            self._set_application(
                application_id,
                status="blocked",
                error=f"restore ownership no longer verifies: {type(exc).__name__}: {exc}",
            )
            return self.inspect_work_restore_application(application_id)

        target = Path(str(app["target_path"]))
        staging = Path(str(app["staging_path"]))
        size_bytes = int(point["size_bytes"])
        content_sha256 = str(point["content_sha256"])
        current = observe_file_identity(target, max_hash_bytes=DEFAULT_MAX_HASH_BYTES)
        if self._content_matches(
            current,
            size_bytes=size_bytes,
            content_sha256=content_sha256,
        ):
            self._discard_exact_stage(
                staging,
                size_bytes=size_bytes,
                content_sha256=content_sha256,
            )
            self._set_application(
                application_id,
                status="completed",
                current_identity=current,
                error=None,
                completed=True,
            )
            return self.inspect_work_restore_application(application_id)

        if self._stable_missing(current):
            self._set_application(
                application_id,
                status="recovery_required",
                current_identity=current,
                error=(
                    "restore application stopped before verified completion; "
                    "fresh explicit approval is required before another no-replace commit"
                ),
            )
            return self.inspect_work_restore_application(application_id)

        stage_removed = self._discard_exact_stage(
            staging,
            size_bytes=size_bytes,
            content_sha256=content_sha256,
        )
        self._set_application(
            application_id,
            status="blocked",
            current_identity=current,
            error=(
                "restore target is no longer missing and will not be overwritten"
                if stage_removed
                else "restore target is no longer missing; unexpected staging evidence remains"
            ),
        )
        return self.inspect_work_restore_application(application_id)

    def reconcile_restore_applications(self) -> int:
        with closing(self._restore_connect()) as conn:
            rows = conn.execute(
                f"SELECT application_id FROM {_APPLICATION_TABLE} "
                "WHERE status IN ('applying','stage_ready','commit_started') "
                "ORDER BY updated_at ASC LIMIT 64"
            ).fetchall()
        repaired = 0
        for row in rows:
            self._reconcile_application(str(row["application_id"]))
            repaired += 1
        return repaired

    def approve_missing_work_restore(
        self,
        thread_id: str,
        application_id: str,
    ) -> dict[str, Any]:
        """Explicitly approve and apply one missing-target restore request.

        Calling this control method is the approval act. It revalidates Work
        ownership, retained-byte integrity, current missing reality, original
        parent-directory identity and any retained stage immediately before the
        no-replace namespace movement. A restart never calls this method
        automatically.
        """

        if os.name != "nt":
            raise RuntimeError("missing-file Work restore application currently requires Windows")
        app = self._application_row(application_id)
        if app is None or str(app["thread_id"]) != str(thread_id or "").strip():
            raise ValueError("unknown Work restore application for thread")
        if str(app["status"]) == "completed":
            return self._application_public(app)
        if str(app["status"]) not in _APPROVABLE_STATUSES:
            raise RuntimeError(
                f"Work restore application is not approvable from status {app['status']}"
            )

        point, _, content = self._owned_restore_point(
            str(app["thread_id"]), str(app["restore_point_id"])
        )
        target = Path(str(app["target_path"]))
        staging = Path(str(app["staging_path"]))
        expected_staging = restore_staging_path(target, str(app["application_id"]))
        if staging != expected_staging:
            self._set_application(
                str(app["application_id"]),
                status="blocked",
                error="durable restore staging path does not match application identity",
            )
            raise RuntimeError("Work restore application staging identity is inconsistent")

        try:
            expected_parent = json.loads(str(app["parent_identity_json"] or "{}"))
        except json.JSONDecodeError as exc:
            self._set_application(
                str(app["application_id"]),
                status="blocked",
                error="durable restore parent identity is malformed",
            )
            raise RuntimeError("Work restore application parent identity is malformed") from exc
        parent = self._observe_parent(target)
        if not (
            self._safe_parent(parent)
            and self._same_parent_identity(expected_parent, parent)
        ):
            self._set_application(
                str(app["application_id"]),
                status="blocked",
                error="restore parent directory changed or is no longer safe",
            )
            raise RuntimeError("Work restore parent directory changed since preparation")

        size_bytes = int(point["size_bytes"])
        content_sha256 = str(point["content_sha256"])
        current = observe_file_identity(target, max_hash_bytes=DEFAULT_MAX_HASH_BYTES)
        if not self._stable_missing(current):
            self._set_application(
                str(app["application_id"]),
                status="blocked",
                current_identity=current,
                error="restore target is no longer missing and will not be overwritten",
            )
            raise RuntimeError("Work restore target is no longer missing")

        application = str(app["application_id"])
        try:
            if os.path.lexists(str(staging)):
                stage_ok, stage_identity = self._stage_matches(
                    staging,
                    size_bytes=size_bytes,
                    content_sha256=content_sha256,
                )
                if not stage_ok:
                    self._set_application(
                        application,
                        status="blocked",
                        error="retained restore stage no longer matches approved exact bytes",
                    )
                    raise RuntimeError("retained Work restore stage failed integrity verification")
                self._set_application(
                    application,
                    status="stage_ready",
                    current_identity=current,
                    stage_identity=stage_identity,
                )
                latest_parent = self._observe_parent(target)
                latest = observe_file_identity(target, max_hash_bytes=DEFAULT_MAX_HASH_BYTES)
                if not (
                    self._stable_missing(latest)
                    and self._safe_parent(latest_parent)
                    and self._same_parent_identity(expected_parent, latest_parent)
                ):
                    raise FileExistsError(
                        "restore namespace changed before reapproved commit"
                    )
                self._set_application(
                    application,
                    status="commit_started",
                    current_identity=latest,
                    stage_identity=stage_identity,
                )
                commit_staged_bytes_to_missing_target_windows(staging, target)
            else:
                self._set_application(
                    application,
                    status="applying",
                    current_identity=current,
                    error=None,
                )

                def after_stage(stage_path: Path) -> None:
                    stage_ok, stage_identity = self._stage_matches(
                        stage_path,
                        size_bytes=size_bytes,
                        content_sha256=content_sha256,
                    )
                    if not stage_ok:
                        raise RuntimeError("new Work restore stage failed exact-byte verification")
                    self._set_application(
                        application,
                        status="stage_ready",
                        stage_identity=stage_identity,
                    )

                def before_commit(stage_path: Path) -> None:
                    latest_parent = self._observe_parent(target)
                    latest = observe_file_identity(
                        target, max_hash_bytes=DEFAULT_MAX_HASH_BYTES
                    )
                    if not (
                        self._stable_missing(latest)
                        and self._safe_parent(latest_parent)
                        and self._same_parent_identity(expected_parent, latest_parent)
                    ):
                        raise FileExistsError("restore namespace changed before commit")
                    stage_ok, stage_identity = self._stage_matches(
                        stage_path,
                        size_bytes=size_bytes,
                        content_sha256=content_sha256,
                    )
                    if not stage_ok:
                        raise RuntimeError("Work restore stage changed before commit")
                    self._set_application(
                        application,
                        status="commit_started",
                        current_identity=latest,
                        stage_identity=stage_identity,
                    )

                restore_bytes_to_missing_target_windows(
                    target,
                    content,
                    token=application,
                    after_stage=after_stage,
                    before_commit=before_commit,
                )

            restored = self._verify_restored_target(
                target,
                size_bytes=size_bytes,
                content_sha256=content_sha256,
            )
            self._set_application(
                application,
                status="completed",
                current_identity=restored,
                error=None,
                completed=True,
            )
            return self.inspect_work_restore_application(application)
        except Exception as exc:
            state = self._reconcile_application(application)
            if state["status"] == "completed":
                return state
            raise RuntimeError(
                f"Work restore did not reach verified completion: {type(exc).__name__}: {exc}"
            ) from exc
