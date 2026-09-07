from __future__ import annotations

"""Authority-safe causal file transfer for exact BrowserScene targets.

Playwright owns provider mechanics (file chooser/download events and transport).
ZN owns action schema, authority, BrowserScene identity, file identity, completion
proof, and rollback ownership.
"""

import os
import stat
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
)
from .file_identity import compare_file_identities, observe_file_identity
from .managed_browser import (
    ManagedBrowserError,
    ManagedBrowserUnavailable,
    _ManagedSession,
)


_SCENE_PREFIX = "browser_scene:"
_FILE_ACTIONS = frozenset({BrowserActionKind.UPLOAD_FILE, BrowserActionKind.DOWNLOAD_FILE})
_MAX_SUGGESTED_FILENAME = 255
_COPY_CHUNK_BYTES = 1024 * 1024
_UPLOAD_POSTCONDITION = "causal_file_chooser_and_exact_input_state_verified"
_DOWNLOAD_POSTCONDITION = "causal_download_and_exact_file_identity_verified"

_UPLOAD_INPUT_STATE_SCRIPT = r"""
(element) => {
  const connected = Boolean(element && element.isConnected);
  const tag = String(element && element.tagName || '').toLowerCase();
  const type = String(element && element.getAttribute && element.getAttribute('type') || '')
    .trim().toLowerCase();
  const files = connected && tag === 'input' && type === 'file' && element.files
    ? Array.from(element.files)
    : [];
  return {
    connected,
    tag,
    input_type: type,
    multiple: Boolean(element && element.multiple),
    count: files.length,
    name: files.length === 1 ? String(files[0].name || '') : '',
    size: files.length === 1 ? Number(files[0].size) : -1,
  };
}
"""


class PlaywrightBrowserSceneFileTransferMixin:
    """Narrow MANAGED-only causal upload/download BrowserScene actions."""

    def open_session(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = True,
    ) -> BrowserSessionIdentity:
        """Create a file-authorized ephemeral context without widening USER sessions."""

        policy = permission or BrowserPermissionContext()
        if not (policy.allow_downloads or policy.allow_uploads):
            return super().open_session(permission=policy, headless=headless)
        if self.plane is not BrowserPlane.MANAGED:
            return super().open_session(permission=policy, headless=headless)

        factory = self._playwright_factory or self._default_playwright_factory
        playwright = browser = context = None
        try:
            playwright = factory().start()
            browser = playwright.chromium.launch(headless=bool(headless))
            identity = BrowserSessionIdentity.create(
                plane=BrowserPlane.MANAGED,
                provider=self.name,
                browser_name="chromium",
                browser_version=str(getattr(browser, "version", "") or ""),
                profile_scope="ephemeral",
            )
            context = browser.new_context(
                accept_downloads=bool(policy.allow_downloads),
                service_workers="block",
            )
            context.set_default_navigation_timeout(self.navigation_timeout_ms)
            context.set_default_timeout(self.action_timeout_ms)
            session = _ManagedSession(
                identity=identity,
                permission=policy,
                playwright=playwright,
                browser=browser,
                context=context,
            )
            self._install_network_boundary(session)
            page = context.new_page()
            page_id = self._register_page(session, page)
            self._sessions[identity.session_id] = session
            self._capture(session, page_id)
            return identity
        except ManagedBrowserError:
            self._best_effort_close(context, browser, playwright)
            raise
        except Exception as exc:
            self._best_effort_close(context, browser, playwright)
            if self._playwright_factory is None and self._looks_like_missing_playwright(exc):
                raise ManagedBrowserUnavailable(
                    "local managed browser file transfer requires the browser dependency and Chromium runtime"
                ) from exc
            raise ManagedBrowserError(
                f"failed to open file-authorized managed browser: {type(exc).__name__}: {exc}"
            ) from exc

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if action.kind not in _FILE_ACTIONS:
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            if session.identity.plane is BrowserPlane.USER:
                raise ManagedBrowserError(
                    f"{action.kind.value} is not permitted on the authorized existing user browser"
                )
            self._validate_file_action_shape(action)
            self._validate_authority(session, action, authority)
            if not authority.permission.allow_page_interaction:
                raise ManagedBrowserError(
                    f"{action.kind.value} requires page-interaction permission"
                )
            if action.kind is BrowserActionKind.UPLOAD_FILE:
                if not authority.permission.allow_uploads:
                    raise ManagedBrowserError("UPLOAD_FILE requires explicit upload permission")
            elif not authority.permission.allow_downloads:
                raise ManagedBrowserError("DOWNLOAD_FILE requires explicit download permission")

            assert action.target is not None
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            if action.kind is BrowserActionKind.UPLOAD_FILE:
                return self._upload_file(session, action, binding)
            return self._download_file(session, action, binding)
        except Exception as exc:
            return self._failure(action, error=f"{type(exc).__name__}: {exc}")

    def _validate_file_action_shape(self, action: BrowserAction) -> None:
        if action.target is None or not str(action.target.selector_hint or "").startswith(_SCENE_PREFIX):
            raise ManagedBrowserError(
                f"{action.kind.value} requires an exact current BrowserScene target"
            )
        if action.kind is BrowserActionKind.UPLOAD_FILE:
            self._scene_action_exact_keys(action.args, {"source_identity"}, "UPLOAD_FILE args")
            self._scene_action_exact_keys(action.expected, set(), "UPLOAD_FILE expected")
            if not isinstance(action.args.get("source_identity"), dict):
                raise ManagedBrowserError(
                    "UPLOAD_FILE args.source_identity must be a File Body identity object"
                )
            return
        self._scene_action_exact_keys(action.args, {"destination_path"}, "DOWNLOAD_FILE args")
        self._scene_action_exact_keys(
            action.expected,
            {"suggested_filename_equals"},
            "DOWNLOAD_FILE expected",
        )
        self._download_destination_path(action.args.get("destination_path"))
        self._safe_expected_filename(action.expected.get("suggested_filename_equals"))

    def _upload_file(self, session: Any, action: BrowserAction, binding: Any) -> BrowserEffectEvidence:
        source_before = self._require_exact_source_identity(action.args["source_identity"])
        source_path = str(source_before["path"])
        source_dispatch = observe_file_identity(source_path)
        self._require_identity_match(source_before, source_dispatch, "upload source changed before dispatch")

        page, before_url, pages_before = self._scene_action_pre_dispatch(session, binding)
        expect_chooser = getattr(page, "expect_file_chooser", None)
        if not callable(expect_chooser):
            raise ManagedBrowserError(
                "browser provider does not support action-scoped file chooser observation"
            )

        dispatched = False
        try:
            self._scene_revalidate_binding(session, binding)
            latest_source = observe_file_identity(source_path)
            self._require_identity_match(
                source_dispatch,
                latest_source,
                "upload source changed immediately before dispatch",
            )
            with expect_chooser(timeout=self.action_timeout_ms) as chooser_info:
                dispatched = True
                binding.handle.click()
            chooser = chooser_info.value
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)

            if chooser is None:
                raise ManagedBrowserError("file chooser expectation returned no FileChooser")
            if self._provider_value(chooser, "page") is not page:
                raise ManagedBrowserError("causal file chooser belongs to a different Page")
            chooser_element = self._provider_value(chooser, "element")
            if chooser_element is None:
                raise ManagedBrowserError("causal file chooser has no element")
            if self._provider_bool(chooser, "is_multiple"):
                raise ManagedBrowserError("UPLOAD_FILE first slice refuses a multiple file chooser")
            before_input = self._upload_input_state(chooser_element)
            if before_input["multiple"]:
                raise ManagedBrowserError("UPLOAD_FILE first slice refuses input[multiple]")

            set_files = getattr(chooser, "set_files", None)
            if not callable(set_files):
                raise ManagedBrowserError("browser provider cannot set files on causal chooser")
            set_files(source_path)

            after_input = self._upload_input_state(chooser_element)
            expected_basename = Path(source_path).name
            expected_size = int(source_before["size_bytes"])
            if after_input["count"] != 1:
                raise ManagedBrowserError("file input postcondition did not contain exactly one file")
            if after_input["name"] != expected_basename:
                raise ManagedBrowserError("file input basename postcondition did not match source")
            if after_input["size"] != expected_size:
                raise ManagedBrowserError("file input size postcondition did not match source identity")

            source_after = observe_file_identity(source_path)
            self._require_identity_match(source_before, source_after, "upload source changed during operation")
            self._require_same_page_postcondition(
                session, binding.page_id, page, before_url, pages_before, label="upload"
            )
            observed = self._capture(session, binding.page_id)
            self._require_url_allowed(observed.url, session.permission)
            if observed.url != before_url:
                raise ManagedBrowserError("UPLOAD_FILE changed the top-level URL")
            self._scene_action_no_fresh_page(session, pages_before)

            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=observed.captured_at,
                success=True,
                page_id=binding.page_id,
                url_before=before_url,
                url_after=observed.url,
                target_id=action.target.target_id if action.target else "",
                postcondition=_UPLOAD_POSTCONDITION,
                data={
                    "provider": session.identity.provider,
                    "frame_id": binding.scene_target.frame_id,
                    "source_path": source_path,
                    "source_size": expected_size,
                    "source_sha256": str(source_before["content_sha256"]),
                    "source_identity_unchanged_after": True,
                    "selected_basename": expected_basename,
                    "selected_size": after_input["size"],
                    "target_revalidated_before_dispatch": True,
                    "chooser_page_matches": True,
                    "page_topology_unchanged": True,
                },
            )
        except Exception:
            if dispatched:
                self._scene_action_dispatched_failure(session, binding.page_id)
            raise

    def _download_file(self, session: Any, action: BrowserAction, binding: Any) -> BrowserEffectEvidence:
        destination = self._download_destination_path(action.args["destination_path"])
        expected_filename = self._safe_expected_filename(
            action.expected["suggested_filename_equals"]
        )
        destination_before = observe_file_identity(destination)
        self._require_missing_destination(destination_before)
        parent_snapshot = self._observe_destination_parent(destination)

        page, before_url, pages_before = self._scene_action_pre_dispatch(session, binding)
        expect_download = getattr(page, "expect_download", None)
        if not callable(expect_download):
            raise ManagedBrowserError(
                "browser provider does not support action-scoped download observation"
            )

        download = None
        dispatched = False
        temp_dir = temp_path = ""
        owned_identity: dict[str, Any] | None = None
        owned_stat: tuple[int, int, int, int, int] | None = None
        try:
            self._scene_revalidate_binding(session, binding)
            self._revalidate_destination_parent(destination, parent_snapshot)
            self._require_identity_match(
                destination_before,
                observe_file_identity(destination),
                "download destination changed before dispatch",
            )

            with expect_download(timeout=self.action_timeout_ms) as download_info:
                dispatched = True
                binding.handle.click()
            download = download_info.value
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)

            if download is None:
                raise ManagedBrowserError("download expectation returned no Download")
            if self._provider_value(download, "page") is not page:
                raise ManagedBrowserError("causal Download belongs to a different Page")
            suggested = str(self._provider_value(download, "suggested_filename") or "")
            if suggested != expected_filename:
                raise ManagedBrowserError("Download suggested_filename did not match exact expectation")
            download_url = str(self._provider_value(download, "url") or "").strip()
            self._require_download_url_allowed(download_url, session.permission)
            failure_fn = getattr(download, "failure", None)
            if not callable(failure_fn):
                raise ManagedBrowserError("browser provider cannot report Download.failure()")
            if failure_fn() is not None:
                raise ManagedBrowserError("causal download provider reported failure")

            temp_dir = tempfile.mkdtemp(prefix="zn-browser-download-")
            temp_path = os.path.join(temp_dir, "payload")
            save_as = getattr(download, "save_as", None)
            if not callable(save_as):
                raise ManagedBrowserError("browser provider cannot persist causal Download")
            save_as(temp_path)
            temp_identity = observe_file_identity(temp_path)
            self._require_complete_regular_identity(temp_identity, label="downloaded temporary file")

            self._revalidate_destination_parent(destination, parent_snapshot)
            self._require_identity_match(
                destination_before,
                observe_file_identity(destination),
                "download destination changed before exclusive commit",
            )
            owned_stat = self._exclusive_copy(temp_path, destination)
            owned_identity = observe_file_identity(destination)
            self._require_complete_regular_identity(owned_identity, label="download destination")
            if int(owned_identity["size_bytes"]) != int(temp_identity["size_bytes"]):
                raise ManagedBrowserError("final download size does not match owned temporary file")
            if str(owned_identity["content_sha256"]) != str(temp_identity["content_sha256"]):
                raise ManagedBrowserError("final download SHA-256 does not match owned temporary file")

            self._require_same_page_postcondition(
                session, binding.page_id, page, before_url, pages_before, label="download"
            )
            observed = self._capture(session, binding.page_id)
            self._require_url_allowed(observed.url, session.permission)
            if observed.url != before_url:
                raise ManagedBrowserError("DOWNLOAD_FILE changed the top-level URL")
            self._scene_action_no_fresh_page(session, pages_before)

            evidence = BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=observed.captured_at,
                success=True,
                page_id=binding.page_id,
                url_before=before_url,
                url_after=observed.url,
                target_id=action.target.target_id if action.target else "",
                postcondition=_DOWNLOAD_POSTCONDITION,
                data={
                    "provider": session.identity.provider,
                    "frame_id": binding.scene_target.frame_id,
                    "destination_path": str(owned_identity["path"]),
                    "suggested_filename": suggested,
                    "download_url": download_url,
                    "download_size": int(owned_identity["size_bytes"]),
                    "download_sha256": str(owned_identity["content_sha256"]),
                    "temp_sha256_matches_final": True,
                    "target_revalidated_before_dispatch": True,
                    "download_page_matches": True,
                    "page_topology_unchanged": True,
                    "exclusive_create_commit": True,
                },
            )
            owned_identity = None
            owned_stat = None
            return evidence
        except Exception:
            if download is not None:
                cancel = getattr(download, "cancel", None)
                if callable(cancel):
                    try:
                        cancel()
                    except Exception:
                        pass
            if owned_identity is not None or owned_stat is not None:
                self._cleanup_owned_destination(destination, owned_identity, owned_stat)
            if dispatched:
                self._scene_action_dispatched_failure(session, binding.page_id)
            raise
        finally:
            self._cleanup_owned_temp(temp_path)
            self._cleanup_owned_temp_dir(temp_dir)

    @staticmethod
    def _provider_value(obj: Any, name: str) -> Any:
        value = getattr(obj, name, None)
        return value() if callable(value) else value

    @classmethod
    def _provider_bool(cls, obj: Any, name: str) -> bool:
        value = cls._provider_value(obj, name)
        if type(value) is not bool:
            raise ManagedBrowserError(f"browser provider did not expose boolean {name}")
        return value

    @staticmethod
    def _require_complete_regular_identity(identity: Any, *, label: str) -> dict[str, Any]:
        if not isinstance(identity, dict):
            raise ManagedBrowserError(f"{label} identity must be a File Body identity object")
        required = {
            "version",
            "path",
            "observable",
            "stable",
            "exists",
            "type",
            "size_bytes",
            "digest_complete",
            "content_sha256",
        }
        if not required.issubset(identity):
            raise ManagedBrowserError(f"{label} identity is incomplete")
        if not bool(identity.get("observable")) or not bool(identity.get("stable")):
            raise ManagedBrowserError(f"{label} identity is not observable and stable")
        if not bool(identity.get("exists")) or identity.get("type") != "file":
            raise ManagedBrowserError(f"{label} must be an existing regular file")
        if not bool(identity.get("digest_complete")) or not str(identity.get("content_sha256") or ""):
            raise ManagedBrowserError(
                f"{label} is outside bounded complete SHA-256 identity scope"
            )
        path = str(identity.get("path") or "")
        if not path or not os.path.isabs(path):
            raise ManagedBrowserError(f"{label} requires a canonical absolute path")
        return dict(identity)

    @classmethod
    def _require_exact_source_identity(cls, identity: Any) -> dict[str, Any]:
        checked = cls._require_complete_regular_identity(identity, label="upload source")
        current = observe_file_identity(str(checked["path"]))
        cls._require_identity_match(checked, current, "upload source identity is stale")
        return checked

    @staticmethod
    def _require_identity_match(previous: dict[str, Any], current: dict[str, Any], error: str) -> None:
        comparison = compare_file_identities(previous, current)
        if not bool(comparison.get("exact")):
            reason = str(comparison.get("reason") or "identity mismatch")
            raise ManagedBrowserError(f"{error}: {reason}")

    @staticmethod
    def _upload_input_state(element: Any) -> dict[str, Any]:
        evaluate = getattr(element, "evaluate", None)
        if not callable(evaluate):
            raise ManagedBrowserError("causal file chooser element is not inspectable")
        raw = evaluate(_UPLOAD_INPUT_STATE_SCRIPT)
        if not isinstance(raw, dict) or not bool(raw.get("connected")):
            raise ManagedBrowserError("causal file chooser element is detached")
        if raw.get("tag") != "input" or raw.get("input_type") != "file":
            raise ManagedBrowserError("causal file chooser element is not input[type=file]")
        count, size = raw.get("count"), raw.get("size")
        if not isinstance(count, int) or isinstance(count, bool):
            raise ManagedBrowserError("file input file count is unavailable")
        if not isinstance(size, (int, float)) or isinstance(size, bool):
            raise ManagedBrowserError("file input selected file size is unavailable")
        return {
            "multiple": bool(raw.get("multiple")),
            "count": int(count),
            "name": str(raw.get("name") or ""),
            "size": int(size),
        }

    @staticmethod
    def _download_destination_path(raw: Any) -> str:
        if not isinstance(raw, str) or not raw.strip():
            raise ManagedBrowserError(
                "DOWNLOAD_FILE args.destination_path must be a non-empty absolute path"
            )
        value = raw.strip()
        if not os.path.isabs(value):
            raise ManagedBrowserError("DOWNLOAD_FILE destination_path must be absolute")
        if "\x00" in value:
            raise ManagedBrowserError("DOWNLOAD_FILE destination_path is invalid")
        return value

    @staticmethod
    def _safe_expected_filename(raw: Any) -> str:
        if not isinstance(raw, str) or not raw:
            raise ManagedBrowserError("suggested_filename_equals must be a non-empty filename")
        if len(raw) > _MAX_SUGGESTED_FILENAME:
            raise ManagedBrowserError("suggested_filename_equals is too long")
        if raw in {".", ".."} or "/" in raw or "\\" in raw:
            raise ManagedBrowserError("suggested_filename_equals must be basename-only")
        if any(ord(char) < 32 or ord(char) == 127 for char in raw):
            raise ManagedBrowserError("suggested_filename_equals contains control characters")
        if Path(raw).name != raw:
            raise ManagedBrowserError("suggested_filename_equals must not contain path traversal")
        return raw

    @staticmethod
    def _require_missing_destination(identity: dict[str, Any]) -> None:
        if not isinstance(identity, dict):
            raise ManagedBrowserError("download destination identity is unavailable")
        if not bool(identity.get("observable")) or not bool(identity.get("stable")):
            raise ManagedBrowserError("download destination missing-state identity is not stable")
        if bool(identity.get("exists")) or identity.get("type") != "missing":
            raise ManagedBrowserError("DOWNLOAD_FILE refuses to overwrite an existing destination")
        if not os.path.isabs(str(identity.get("path") or "")):
            raise ManagedBrowserError("download destination identity is not canonical and absolute")

    @classmethod
    def _assert_no_symlink_components(cls, parent: Path) -> None:
        current = Path(parent.anchor)
        for part in parent.parts[1:]:
            current = current / part
            try:
                info = os.lstat(current)
            except OSError as exc:
                raise ManagedBrowserError(
                    f"download destination parent is unavailable: {type(exc).__name__}: {exc}"
                ) from exc
            if stat.S_ISLNK(info.st_mode):
                raise ManagedBrowserError("download destination parent path contains a symlink")
            is_junction = getattr(current, "is_junction", None)
            if callable(is_junction) and is_junction():
                raise ManagedBrowserError("download destination parent path contains a junction")

    @classmethod
    def _observe_destination_parent(cls, destination: str) -> dict[str, Any]:
        parent = Path(destination).parent
        cls._assert_no_symlink_components(parent)
        try:
            raw_stat = os.lstat(parent)
        except OSError as exc:
            raise ManagedBrowserError(
                f"download destination parent is unavailable: {type(exc).__name__}: {exc}"
            ) from exc
        if not stat.S_ISDIR(raw_stat.st_mode):
            raise ManagedBrowserError("download destination parent must be an existing directory")
        identity = observe_file_identity(str(parent), max_hash_bytes=0)
        if not bool(identity.get("observable")) or not bool(identity.get("stable")):
            raise ManagedBrowserError("download destination parent identity is not stable")
        if not bool(identity.get("exists")) or identity.get("type") != "directory":
            raise ManagedBrowserError("download destination parent is not a stable directory")
        return {
            "path": str(identity.get("path") or ""),
            "device": int(getattr(raw_stat, "st_dev", 0)),
            "inode": int(getattr(raw_stat, "st_ino", 0)),
            "size_bytes": int(getattr(raw_stat, "st_size", 0)),
            "mtime_ns": int(getattr(raw_stat, "st_mtime_ns", 0)),
            "ctime_ns": int(getattr(raw_stat, "st_ctime_ns", 0)),
        }

    @classmethod
    def _revalidate_destination_parent(cls, destination: str, previous: dict[str, Any]) -> None:
        if cls._observe_destination_parent(destination) != previous:
            raise ManagedBrowserError("download destination parent identity changed before commit")

    def _require_download_url_allowed(self, url: str, permission: BrowserPermissionContext) -> None:
        if not url:
            raise ManagedBrowserError("causal Download URL is unavailable")
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise ManagedBrowserError("causal Download URL is invalid") from exc
        if str(parsed.scheme or "").lower() not in {"http", "https"} or not parsed.hostname:
            raise ManagedBrowserError(
                "DOWNLOAD_FILE first slice requires an HTTP(S) download URL"
            )
        self._require_url_allowed(url, permission)

    @staticmethod
    def _stat_marker(info: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            int(getattr(info, "st_dev", 0)),
            int(getattr(info, "st_ino", 0)),
            int(getattr(info, "st_size", 0)),
            int(getattr(info, "st_mtime_ns", 0)),
            int(getattr(info, "st_ctime_ns", 0)),
        )

    @classmethod
    def _exclusive_copy(cls, source: str, destination: str) -> tuple[int, int, int, int, int]:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            fd = os.open(destination, flags, 0o600)
        except FileExistsError as exc:
            raise ManagedBrowserError(
                "download destination was created concurrently; refusing overwrite"
            ) from exc
        except OSError as exc:
            raise ManagedBrowserError(
                f"exclusive download destination create failed: {type(exc).__name__}: {exc}"
            ) from exc

        owned: tuple[int, int, int, int, int] | None = None
        try:
            with open(source, "rb") as reader, os.fdopen(fd, "wb", closefd=True) as writer:
                fd = -1
                try:
                    while True:
                        chunk = reader.read(_COPY_CHUNK_BYTES)
                        if not chunk:
                            break
                        writer.write(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                    owned = cls._stat_marker(os.fstat(writer.fileno()))
                except Exception:
                    try:
                        owned = cls._stat_marker(os.fstat(writer.fileno()))
                    except OSError:
                        owned = None
                    raise
            assert owned is not None
            return owned
        except Exception:
            if fd >= 0:
                try:
                    owned = cls._stat_marker(os.fstat(fd))
                except OSError:
                    owned = None
                try:
                    os.close(fd)
                except OSError:
                    pass
            if owned is not None:
                cls._cleanup_owned_destination(destination, None, owned)
            raise

    @classmethod
    def _cleanup_owned_destination(
        cls,
        destination: str,
        identity: dict[str, Any] | None,
        owned_stat: tuple[int, int, int, int, int] | None,
    ) -> bool:
        try:
            info = os.lstat(destination)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        if not stat.S_ISREG(info.st_mode):
            return False
        if owned_stat is None or cls._stat_marker(info) != owned_stat:
            return False
        if identity is not None:
            try:
                comparison = compare_file_identities(identity, observe_file_identity(destination))
                if not bool(comparison.get("exact")):
                    return False
            except Exception:
                return False
        try:
            os.unlink(destination)
            return True
        except OSError:
            return False

    @staticmethod
    def _cleanup_owned_temp(path: str) -> None:
        if not path:
            return
        try:
            os.unlink(path)
        except (FileNotFoundError, OSError):
            pass

    @staticmethod
    def _cleanup_owned_temp_dir(path: str) -> None:
        if not path:
            return
        try:
            os.rmdir(path)
        except OSError:
            pass

    def _require_same_page_postcondition(
        self,
        session: Any,
        page_id: str,
        page: Any,
        before_url: str,
        pages_before: tuple[Any, ...],
        *,
        label: str,
    ) -> None:
        current_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(current_url, session.permission)
        if current_url != before_url:
            raise ManagedBrowserError(f"{label} unexpectedly changed the top-level URL")
        self._scene_action_no_fresh_page(session, pages_before)
        if page_id not in session.pages or session.pages.get(page_id) is not page:
            raise ManagedBrowserError(f"{label} exact Page identity is no longer live")
