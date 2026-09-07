from __future__ import annotations

"""Causal BrowserScene upload/download actions bound to real file identity evidence."""

import os
from pathlib import Path
from typing import Any

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
)
from .file_identity import compare_file_identities, observe_file_identity
from .managed_browser import ManagedBrowserError
from .models import utc_now


_SCENE_SELECTOR_PREFIX = "browser_scene:"
_TRANSFER_TRIGGER_ROLES = frozenset({"button", "link"})
_MAX_FILENAME_CHARS = 255

_FILE_INPUT_STATE_SCRIPT = r"""
(element) => {
  if (!element || !element.isConnected) return { connected: false };
  const tag = String(element.tagName || "").toLowerCase();
  const type = String(element.getAttribute?.("type") || "").toLowerCase();
  const supported = tag === "input" && type === "file";
  const files = supported ? Array.from(element.files || []) : [];
  return {
    connected: true,
    supported,
    multiple: Boolean(element.multiple),
    count: files.length,
    files: files.map((file) => ({
      name: String(file.name || ""),
      size: Number(file.size || 0),
      type: String(file.type || ""),
    })),
  };
}
"""


class PlaywrightBrowserSceneFileTransferMixin:
    """Upload/download one file through one exact current BrowserScene trigger."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._is_scene_transfer_action(action):
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.target is None:
                raise ManagedBrowserError(
                    "BrowserScene file transfer requires a current trigger target"
                )
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            if action.kind is BrowserActionKind.UPLOAD_FILE:
                return self._scene_upload_file(session, action, binding)
            return self._scene_download_file(session, action, binding)
        except Exception as exc:
            return self._failure(action, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _is_scene_transfer_action(action: BrowserAction) -> bool:
        return bool(
            action.kind in {BrowserActionKind.UPLOAD_FILE, BrowserActionKind.DOWNLOAD_FILE}
            and action.target is not None
            and str(action.target.selector_hint or "").startswith(_SCENE_SELECTOR_PREFIX)
        )

    def _scene_upload_file(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
    ) -> BrowserEffectEvidence:
        self._require_transfer_trigger(binding, kind="upload")
        if set(action.args) != {"source_identity"}:
            raise ManagedBrowserError(
                "BrowserScene upload_file requires exactly one source_identity argument"
            )
        if action.expected:
            raise ManagedBrowserError(
                "BrowserScene upload_file first slice does not accept page/navigation postconditions"
            )
        expected_identity = action.args.get("source_identity")
        if not isinstance(expected_identity, dict):
            raise ManagedBrowserError("BrowserScene upload source_identity must be an object")
        source_path = str(expected_identity.get("path") or "")
        if not source_path:
            raise ManagedBrowserError("BrowserScene upload source identity has no canonical path")
        current_identity = observe_file_identity(source_path)
        comparison = compare_file_identities(expected_identity, current_identity)
        if not comparison.get("exact"):
            raise ManagedBrowserError(
                f"BrowserScene upload source identity is stale: {comparison.get('reason')}"
            )
        if current_identity.get("type") != "file" or not current_identity.get("digest_complete"):
            raise ManagedBrowserError(
                "BrowserScene upload first slice requires one stable regular file with complete digest"
            )

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        self._reconcile_pages(session)
        before_page_ids = set(session.pages)
        expect_file_chooser = getattr(page, "expect_file_chooser", None)
        if not callable(expect_file_chooser):
            raise ManagedBrowserError(
                "browser provider cannot causally observe a file chooser from the trigger page"
            )

        try:
            with expect_file_chooser() as chooser_info:
                binding.handle.click()
            chooser = chooser_info.value
            if chooser is None:
                raise ManagedBrowserError("browser provider did not return a file chooser")
            set_files = getattr(chooser, "set_files", None)
            if not callable(set_files):
                raise ManagedBrowserError("browser file chooser cannot set files")
            set_files(source_path)
        except ManagedBrowserError:
            self._scene_failed_mutation(session, binding.page_id)
            raise
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene upload dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        self._reconcile_pages(session)
        new_page_ids = tuple(
            page_id for page_id in session.pages if page_id not in before_page_ids
        )
        after_url = str(getattr(page, "url", "") or "")
        if new_page_ids or after_url != before_url or not self._url_allowed(after_url, session.permission):
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=utc_now(),
                success=False,
                page_id=binding.page_id,
                url_before=before_url,
                url_after=after_url if self._url_allowed(after_url, session.permission) else "",
                target_id=action.target.target_id,
                postcondition="causal_file_chooser_exact_source_identity",
                data={
                    "provider": session.identity.provider,
                    "new_page_ids": list(new_page_ids),
                    "source_size_bytes": current_identity.get("size_bytes"),
                    "source_content_sha256": current_identity.get("content_sha256"),
                },
                error=(
                    "BrowserScene upload changed page topology or URL unexpectedly"
                ),
            )

        input_state = self._file_chooser_input_state(chooser)
        after_identity = observe_file_identity(source_path)
        after_comparison = compare_file_identities(current_identity, after_identity)
        expected_name = Path(source_path).name
        files = input_state.get("files") if isinstance(input_state, dict) else None
        file_row = files[0] if isinstance(files, list) and len(files) == 1 else None
        success = bool(
            after_comparison.get("exact")
            and input_state.get("connected")
            and input_state.get("supported")
            and not input_state.get("multiple")
            and input_state.get("count") == 1
            and isinstance(file_row, dict)
            and str(file_row.get("name") or "") == expected_name
            and int(file_row.get("size") or -1) == int(current_identity.get("size_bytes") or -2)
        )
        self._scene_invalidate_page(session.identity.session_id, binding.page_id)
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=after_url,
            target_id=action.target.target_id,
            postcondition="causal_file_chooser_exact_source_identity",
            data={
                "provider": session.identity.provider,
                "frame_id": binding.scene_target.frame_id,
                "source_path": str(current_identity.get("path") or ""),
                "source_size_bytes": current_identity.get("size_bytes"),
                "source_content_sha256": current_identity.get("content_sha256"),
                "source_identity_unchanged_after": bool(after_comparison.get("exact")),
                "file_input_count": input_state.get("count"),
                "file_input_name": str(file_row.get("name") or "") if isinstance(file_row, dict) else "",
                "file_input_size_bytes": int(file_row.get("size") or 0) if isinstance(file_row, dict) else 0,
                "new_page_ids": [],
                "target_revalidated_before_dispatch": True,
            },
            error=None if success else "BrowserScene upload postcondition was not proven",
        )

    def _scene_download_file(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
    ) -> BrowserEffectEvidence:
        self._require_transfer_trigger(binding, kind="download")
        if set(action.args) != {"destination_path"}:
            raise ManagedBrowserError(
                "BrowserScene download_file requires exactly one destination_path argument"
            )
        if set(action.expected) != {"suggested_filename_equals"}:
            raise ManagedBrowserError(
                "BrowserScene download_file requires explicit suggested_filename_equals"
            )
        destination_raw = action.args.get("destination_path")
        if not isinstance(destination_raw, str) or not destination_raw.strip():
            raise ManagedBrowserError("BrowserScene download destination_path must be non-empty")
        expected_filename = str(action.expected.get("suggested_filename_equals") or "").strip()
        if not expected_filename or len(expected_filename) > _MAX_FILENAME_CHARS:
            raise ManagedBrowserError(
                "BrowserScene download suggested filename is empty or too long"
            )
        if expected_filename != os.path.basename(expected_filename):
            raise ManagedBrowserError(
                "BrowserScene download suggested filename must not contain path components"
            )

        destination_before = observe_file_identity(destination_raw)
        if not (
            destination_before.get("observable")
            and destination_before.get("stable")
            and destination_before.get("exists") is False
            and destination_before.get("type") == "missing"
        ):
            raise ManagedBrowserError(
                "BrowserScene download first slice refuses to overwrite an existing/unobservable target"
            )
        destination_path = str(destination_before.get("path") or "")
        parent_identity = observe_file_identity(str(Path(destination_path).parent), max_hash_bytes=0)
        if not (
            parent_identity.get("observable")
            and parent_identity.get("stable")
            and parent_identity.get("exists") is True
            and parent_identity.get("type") == "directory"
        ):
            raise ManagedBrowserError(
                "BrowserScene download destination parent must already exist as a stable directory"
            )

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        self._reconcile_pages(session)
        before_page_ids = set(session.pages)
        expect_download = getattr(page, "expect_download", None)
        if not callable(expect_download):
            raise ManagedBrowserError(
                "browser provider cannot causally observe a download from the trigger page"
            )

        try:
            with expect_download() as download_info:
                binding.handle.click()
            download = download_info.value
            if download is None:
                raise ManagedBrowserError("browser provider did not return a download")
            suggested = str(getattr(download, "suggested_filename", "") or "")
            if suggested != expected_filename:
                cancel = getattr(download, "cancel", None)
                if callable(cancel):
                    cancel()
                raise ManagedBrowserError(
                    "BrowserScene download suggested filename did not match expectation"
                )
            save_as = getattr(download, "save_as", None)
            if not callable(save_as):
                raise ManagedBrowserError("browser download cannot save_as an explicit path")
            save_as(destination_path)
        except ManagedBrowserError:
            self._scene_failed_mutation(session, binding.page_id)
            raise
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene download dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        self._reconcile_pages(session)
        new_page_ids = tuple(
            page_id for page_id in session.pages if page_id not in before_page_ids
        )
        after_url = str(getattr(page, "url", "") or "")
        destination_after = observe_file_identity(destination_path)
        success = bool(
            not new_page_ids
            and after_url == before_url
            and self._url_allowed(after_url, session.permission)
            and destination_after.get("observable")
            and destination_after.get("stable")
            and destination_after.get("exists") is True
            and destination_after.get("type") == "file"
        )
        self._scene_invalidate_page(session.identity.session_id, binding.page_id)
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=str(destination_after.get("observed_at") or utc_now()),
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=after_url if self._url_allowed(after_url, session.permission) else "",
            target_id=action.target.target_id,
            postcondition="causal_download_saved_as_new_stable_file",
            data={
                "provider": session.identity.provider,
                "frame_id": binding.scene_target.frame_id,
                "suggested_filename": expected_filename,
                "destination_path": destination_path,
                "destination_size_bytes": destination_after.get("size_bytes"),
                "destination_digest_complete": bool(destination_after.get("digest_complete")),
                "destination_content_sha256": destination_after.get("content_sha256"),
                "new_page_ids": list(new_page_ids),
                "target_revalidated_before_dispatch": True,
            },
            error=None if success else "BrowserScene download postcondition was not proven",
        )

    @staticmethod
    def _require_transfer_trigger(binding: Any, *, kind: str) -> None:
        role = str(binding.scene_target.role or "")
        if role not in _TRANSFER_TRIGGER_ROLES:
            raise ManagedBrowserError(
                f"BrowserScene {kind} trigger supports button/link targets only"
            )

    @staticmethod
    def _file_chooser_input_state(chooser: Any) -> dict[str, Any]:
        element = getattr(chooser, "element", None)
        if element is None:
            raise ManagedBrowserError("browser file chooser exposes no input element")
        raw = element.evaluate(_FILE_INPUT_STATE_SCRIPT)
        if not isinstance(raw, dict):
            raise ManagedBrowserError("browser file chooser returned invalid input evidence")
        return raw
