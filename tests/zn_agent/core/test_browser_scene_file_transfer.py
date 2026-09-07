from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
    BrowserTarget,
    BrowserTargetKind,
)
from zn_agent.core.browser_scene_file_transfer import PlaywrightBrowserSceneFileTransferMixin
from zn_agent.core.file_identity import DEFAULT_MAX_HASH_BYTES, observe_file_identity
from zn_agent.core.models import utc_now


class _EventInfo:
    def __init__(self, value, *, error=None):
        self.value = value
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None and self.error is not None:
            raise self.error
        return False


class _ChooserElement:
    def __init__(self, chooser):
        self.chooser = chooser
        self.connected = True
        self.tag = "input"
        self.input_type = "file"
        self.multiple = False
        self.force_name = None
        self.force_size = None

    def evaluate(self, _script):
        path = self.chooser.path
        if path:
            file_path = Path(path)
            count = 1
            name = self.force_name if self.force_name is not None else file_path.name
            size = self.force_size if self.force_size is not None else file_path.stat().st_size
        else:
            count, name, size = 0, "", -1
        return {
            "connected": self.connected,
            "tag": self.tag,
            "input_type": self.input_type,
            "multiple": self.multiple,
            "count": count,
            "name": name,
            "size": size,
        }


class _Chooser:
    def __init__(self, page):
        self.page = page
        self.path = ""
        self.element = _ChooserElement(self)
        self.multiple = False
        self.after_set = None

    def is_multiple(self):
        return self.multiple

    def set_files(self, path):
        self.path = str(path)
        if self.after_set:
            self.after_set()


class _Download:
    def __init__(self, page, *, content=b"downloaded", suggested="report.bin", url=None):
        self.page = page
        self.content = content
        self.suggested_filename = suggested
        self.url = url or page.url + "/download"
        self.failure_value = None
        self.cancel_calls = 0
        self.saved_path = ""
        self.after_save = None

    def failure(self):
        return self.failure_value

    def save_as(self, path):
        self.saved_path = str(path)
        Path(path).write_bytes(self.content)
        if self.after_save:
            self.after_save()

    def cancel(self):
        self.cancel_calls += 1


class _Page:
    def __init__(self, url="https://example.test/start"):
        self.url = url
        self.chooser = _Chooser(self)
        self.download = _Download(self)
        self.chooser_error = None
        self.download_error = None
        self.chooser_timeout = None
        self.download_timeout = None

    def expect_file_chooser(self, *, timeout):
        self.chooser_timeout = timeout
        return _EventInfo(self.chooser, error=self.chooser_error)

    def expect_download(self, *, timeout):
        self.download_timeout = timeout
        return _EventInfo(self.download, error=self.download_error)


class _Handle:
    def __init__(self):
        self.click_calls = 0
        self.on_click = None

    def click(self):
        self.click_calls += 1
        if self.on_click:
            self.on_click()


class _Base:
    def act(self, action, authority):
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            error="delegated",
            data={"delegated_kind": action.kind.value},
        )


class _Harness(PlaywrightBrowserSceneFileTransferMixin, _Base):
    action_timeout_ms = 1234

    def __init__(self, permission, *, plane=BrowserPlane.MANAGED):
        identity = BrowserSessionIdentity.create(
            plane=plane,
            provider="fake",
            profile_scope="user_existing" if plane is BrowserPlane.USER else "ephemeral",
        )
        self.page = _Page()
        self.context = SimpleNamespace(pages=[self.page])
        self.handle = _Handle()
        self.invalidated = []
        self.revalidate_calls = 0
        self.fail_revalidate_at = None
        self.capture_calls = 0
        self.session = SimpleNamespace(
            identity=identity,
            permission=permission,
            context=self.context,
            pages={"page-1": self.page},
            default_page_id="page-1",
            last_observation={},
        )
        self.target = BrowserTarget(
            session_id=identity.session_id,
            page_id="page-1",
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="scene-transfer",
            observed_at=utc_now(),
            url=self.page.url,
            frame_id="main",
            role="button",
            name="Transfer",
            selector_hint="browser_scene:button",
        )
        self.binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=self.handle,
            scene_target=SimpleNamespace(role="button", frame_id="main"),
        )

    def _session(self, session_id):
        if session_id != self.session.identity.session_id:
            raise RuntimeError("unknown session")
        return self.session

    def _validate_authority(self, session, action, authority):
        if authority.session_id != session.identity.session_id:
            raise RuntimeError("authority session mismatch")
        if authority.permission != session.permission:
            raise RuntimeError("authority permission mismatch")
        if not authority.permission.allows_action(action.kind):
            raise RuntimeError(f"browser action is not permitted: {action.kind.value}")

    def _scene_action_binding(self, session, target_id, *, page_id="", expected_target=None):
        if target_id != self.target.target_id:
            raise RuntimeError("stale target")
        if expected_target is not None and expected_target != self.target:
            raise RuntimeError("target evidence changed")
        return self.binding

    def _scene_revalidate_binding(self, session, binding):
        self.revalidate_calls += 1
        if self.fail_revalidate_at == self.revalidate_calls:
            raise RuntimeError("scene binding stale")
        return binding

    def _scene_action_pre_dispatch(self, session, binding):
        self._scene_revalidate_binding(session, binding)
        self._require_url_allowed(self.page.url, session.permission)
        return self.page, self.page.url, tuple(self.context.pages)

    def _scene_action_no_fresh_page(self, session, before):
        current = tuple(self.context.pages)
        if any(not any(page is old for old in before) for page in current):
            raise RuntimeError("unexpected fresh page observed")

    def _scene_invalidate_page(self, session_id, page_id):
        self.invalidated.append(("invalidate", page_id))

    def _scene_action_dispatched_failure(self, session, page_id):
        self.invalidated.append(("failed", page_id))

    @staticmethod
    def _scene_action_exact_keys(value, allowed, label):
        actual = set(value)
        if actual != allowed:
            raise RuntimeError(f"{label} schema mismatch")

    def _capture(self, session, page_id):
        self.capture_calls += 1
        return BrowserObservation(
            session=session.identity,
            page_id=page_id,
            captured_at=utc_now(),
            url=self.page.url,
            title="fixture",
            load_state="complete",
        )

    @staticmethod
    def _require_url_allowed(url, permission):
        if not permission.allows_origin(url):
            raise RuntimeError("url outside authority")

    def _failure(self, action, *, error):
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=action.page_id,
            target_id=action.target.target_id if action.target else "",
            error=error,
        )


def _authority(harness, action, permission=None):
    permission = permission or harness.session.permission
    return BrowserActionAuthority(
        action_id=action.action_id,
        session_id=action.session_id,
        issued_at=utc_now(),
        observation_captured_at=harness.target.observed_at,
        permission=permission,
        target_id=harness.target.target_id,
        page_id="page-1",
    )


def _action(harness, kind, *, args=None, expected=None, target=True):
    return BrowserAction.create(
        session_id=harness.session.identity.session_id,
        page_id="page-1",
        kind=kind,
        target=harness.target if target else None,
        args=args,
        expected=expected,
    )


def _act(harness, kind, *, args=None, expected=None, authority_permission=None):
    action = _action(harness, kind, args=args, expected=expected)
    return action, harness.act(action, _authority(harness, action, authority_permission))


class BrowserSceneFileTransferContractTests(unittest.TestCase):
    def test_action_kind_and_permission_contract(self):
        self.assertEqual(BrowserActionKind.UPLOAD_FILE.value, "upload_file")
        self.assertEqual(BrowserActionKind.DOWNLOAD_FILE.value, "download_file")
        self.assertFalse(BrowserPermissionContext(allow_uploads=True).allows_action(BrowserActionKind.UPLOAD_FILE))
        self.assertFalse(BrowserPermissionContext(allow_page_interaction=True).allows_action(BrowserActionKind.UPLOAD_FILE))
        self.assertTrue(BrowserPermissionContext(allow_page_interaction=True, allow_uploads=True).allows_action(BrowserActionKind.UPLOAD_FILE))
        self.assertFalse(BrowserPermissionContext(allow_downloads=True).allows_action(BrowserActionKind.DOWNLOAD_FILE))
        self.assertFalse(BrowserPermissionContext(allow_page_interaction=True).allows_action(BrowserActionKind.DOWNLOAD_FILE))
        self.assertTrue(BrowserPermissionContext(allow_page_interaction=True, allow_downloads=True).allows_action(BrowserActionKind.DOWNLOAD_FILE))

    def test_user_plane_upload_and_download_fail_before_provider_dispatch(self):
        permission = BrowserPermissionContext(
            allow_page_interaction=True, allow_uploads=True, allow_downloads=True
        )
        harness = _Harness(permission, plane=BrowserPlane.USER)
        for kind, args, expected in (
            (BrowserActionKind.UPLOAD_FILE, {"source_identity": {}}, {}),
            (BrowserActionKind.DOWNLOAD_FILE, {"destination_path": os.path.abspath("x")}, {"suggested_filename_equals": "x"}),
        ):
            _, evidence = _act(harness, kind, args=args, expected=expected)
            self.assertFalse(evidence.success)
            self.assertIn("existing user browser", evidence.error or "")
            self.assertEqual(harness.handle.click_calls, 0)

    def test_malformed_and_extra_schema_fields_fail_closed(self):
        permission = BrowserPermissionContext(allow_page_interaction=True, allow_uploads=True, allow_downloads=True)
        harness = _Harness(permission)
        cases = [
            (BrowserActionKind.UPLOAD_FILE, {}, {}),
            (BrowserActionKind.UPLOAD_FILE, {"source_identity": {}, "extra": 1}, {}),
            (BrowserActionKind.UPLOAD_FILE, {"source_identity": {}}, {"extra": 1}),
            (BrowserActionKind.DOWNLOAD_FILE, {}, {"suggested_filename_equals": "x"}),
            (BrowserActionKind.DOWNLOAD_FILE, {"destination_path": os.path.abspath("x"), "extra": 1}, {"suggested_filename_equals": "x"}),
            (BrowserActionKind.DOWNLOAD_FILE, {"destination_path": os.path.abspath("x")}, {}),
        ]
        for kind, args, expected in cases:
            _, evidence = _act(harness, kind, args=args, expected=expected)
            self.assertFalse(evidence.success)
            self.assertEqual(harness.handle.click_calls, 0)

    def test_non_file_actions_delegate_unchanged(self):
        permission = BrowserPermissionContext(allow_page_interaction=True, allow_navigation=True)
        harness = _Harness(permission)
        for kind in (BrowserActionKind.CLICK, BrowserActionKind.FOCUS, BrowserActionKind.SWITCH_TAB):
            action = _action(harness, kind)
            effect = harness.act(action, _authority(harness, action))
            self.assertEqual(effect.error, "delegated")
            self.assertEqual(effect.data["delegated_kind"], kind.value)


class BrowserSceneUploadTests(unittest.TestCase):
    def _permission(self):
        return BrowserPermissionContext(allow_page_interaction=True, allow_uploads=True)

    def test_exact_source_identity_success_and_content_not_in_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "secret.txt"
            secret = "do-not-leak-this-content"
            source.write_text(secret, encoding="utf-8")
            identity = observe_file_identity(source)
            harness = _Harness(self._permission())
            _, evidence = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": identity}, expected={})
            self.assertTrue(evidence.success, evidence.error)
            self.assertEqual(harness.page.chooser.path, str(source))
            self.assertEqual(evidence.data["source_sha256"], hashlib.sha256(secret.encode()).hexdigest())
            self.assertEqual(evidence.data["source_size"], len(secret.encode()))
            self.assertNotIn(secret, repr(evidence.data))
            self.assertTrue(evidence.data["source_identity_unchanged_after"])
            self.assertTrue(evidence.data["page_topology_unchanged"])
            self.assertEqual(harness.page.chooser_timeout, harness.action_timeout_ms)

    def test_stale_changed_replaced_missing_directory_symlink_and_incomplete_sources_refuse_before_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = []
            changed = root / "changed.txt"
            changed.write_text("before")
            changed_identity = observe_file_identity(changed)
            changed.write_text("after")
            cases.append(changed_identity)

            replaced = root / "replaced.txt"
            replaced.write_text("one")
            replaced_identity = observe_file_identity(replaced)
            replaced.unlink()
            replaced.write_text("two")
            cases.append(replaced_identity)

            missing = root / "missing.txt"
            cases.append(observe_file_identity(missing))
            cases.append(observe_file_identity(root))

            symlink = root / "link.txt"
            target = root / "target.txt"
            target.write_text("target")
            try:
                symlink.symlink_to(target)
                cases.append(observe_file_identity(symlink))
            except OSError:
                pass

            large = root / "large.bin"
            large.write_bytes(b"x" * (DEFAULT_MAX_HASH_BYTES + 1))
            cases.append(observe_file_identity(large))

            for identity in cases:
                harness = _Harness(self._permission())
                _, evidence = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": identity}, expected={})
                self.assertFalse(evidence.success)
                self.assertEqual(harness.handle.click_calls, 0)

    def test_chooser_timeout_invalidates_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "a.txt"
            source.write_text("a")
            harness = _Harness(self._permission())
            harness.page.chooser_error = TimeoutError("chooser timeout")
            _, evidence = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": observe_file_identity(source)}, expected={})
            self.assertFalse(evidence.success)
            self.assertEqual(harness.handle.click_calls, 1)
            self.assertIn(("failed", "page-1"), harness.invalidated)

    def test_wrong_chooser_page_missing_element_non_file_and_multiple_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "a.txt"
            source.write_text("a")
            identity = observe_file_identity(source)

            harness = _Harness(self._permission())
            harness.page.chooser.page = _Page()
            _, evidence = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": identity}, expected={})
            self.assertFalse(evidence.success)
            self.assertIn("different Page", evidence.error or "")

            harness = _Harness(self._permission())
            harness.page.chooser.element = None
            _, evidence = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": identity}, expected={})
            self.assertFalse(evidence.success)
            self.assertIn("no element", evidence.error or "")

            harness = _Harness(self._permission())
            harness.page.chooser.element.tag = "button"
            _, evidence = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": identity}, expected={})
            self.assertFalse(evidence.success)
            self.assertIn("input[type=file]", evidence.error or "")

            harness = _Harness(self._permission())
            harness.page.chooser.multiple = True
            _, evidence = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": identity}, expected={})
            self.assertFalse(evidence.success)
            self.assertIn("multiple", evidence.error or "")

    def test_input_postcondition_source_change_url_change_and_fresh_page_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "a.txt"
            source.write_text("alpha")
            identity = observe_file_identity(source)

            harness = _Harness(self._permission())
            harness.page.chooser.element.force_name = "wrong.txt"
            _, effect = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": identity}, expected={})
            self.assertFalse(effect.success)

            source.write_text("alpha")
            identity = observe_file_identity(source)
            harness = _Harness(self._permission())
            harness.page.chooser.after_set = lambda: source.write_text("changed")
            _, effect = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": identity}, expected={})
            self.assertFalse(effect.success)
            self.assertIn("changed during operation", effect.error or "")

            source.write_text("alpha")
            identity = observe_file_identity(source)
            harness = _Harness(self._permission())
            harness.page.chooser.after_set = lambda: setattr(harness.page, "url", "https://example.test/other")
            _, effect = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": identity}, expected={})
            self.assertFalse(effect.success)

            source.write_text("alpha")
            identity = observe_file_identity(source)
            harness = _Harness(self._permission())
            harness.page.chooser.after_set = lambda: harness.context.pages.append(_Page())
            _, effect = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": identity}, expected={})
            self.assertFalse(effect.success)
            self.assertEqual(len(harness.context.pages), 2)

    def test_stale_scene_binding_refuses_before_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "a.txt"
            source.write_text("a")
            harness = _Harness(self._permission())
            harness.fail_revalidate_at = 1
            _, evidence = _act(harness, BrowserActionKind.UPLOAD_FILE, args={"source_identity": observe_file_identity(source)}, expected={})
            self.assertFalse(evidence.success)
            self.assertEqual(harness.handle.click_calls, 0)


class BrowserSceneDownloadTests(unittest.TestCase):
    def _permission(self, *, origins=()):
        return BrowserPermissionContext(
            allow_page_interaction=True,
            allow_downloads=True,
            allowed_origins=origins,
        )

    def _success(self, tmp, *, content=b"exact-download-bytes"):
        destination = Path(tmp) / "final.bin"
        harness = _Harness(self._permission())
        harness.page.download = _Download(harness.page, content=content, suggested="report.bin")
        _, evidence = _act(
            harness,
            BrowserActionKind.DOWNLOAD_FILE,
            args={"destination_path": str(destination)},
            expected={"suggested_filename_equals": "report.bin"},
        )
        return harness, destination, evidence

    def test_exact_causal_download_uses_hash_and_exclusive_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = b"exact-download-bytes"
            harness, destination, evidence = self._success(tmp, content=content)
            self.assertTrue(evidence.success, evidence.error)
            self.assertEqual(destination.read_bytes(), content)
            self.assertEqual(evidence.data["download_sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(evidence.data["download_size"], len(content))
            self.assertTrue(evidence.data["temp_sha256_matches_final"])
            self.assertTrue(evidence.data["exclusive_create_commit"])
            self.assertFalse(Path(harness.page.download.saved_path).exists())
            self.assertEqual(harness.page.download_timeout, harness.action_timeout_ms)

    def test_wrong_filename_timeout_page_mismatch_provider_failure_and_url_scope_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "final.bin"

            harness = _Harness(self._permission())
            harness.page.download = _Download(harness.page, suggested="wrong.bin")
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(destination)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertFalse(destination.exists())

            harness = _Harness(self._permission())
            harness.page.download_error = TimeoutError("download timeout")
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(destination)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertEqual(harness.handle.click_calls, 1)
            self.assertFalse(destination.exists())

            harness = _Harness(self._permission())
            harness.page.download = _Download(_Page(), suggested="report.bin")
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(destination)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertIn("different Page", effect.error or "")

            harness = _Harness(self._permission())
            harness.page.download.failure_value = "net::ERR_FAILED"
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(destination)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertFalse(destination.exists())

            scoped = BrowserPermissionContext(allow_page_interaction=True, allow_downloads=True, allowed_origins=("https://example.test",))
            harness = _Harness(scoped)
            harness.page.download.url = "https://other.test/file"
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(destination)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertFalse(destination.exists())

    def test_existing_destination_parent_missing_and_bad_filename_fail_before_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "existing.bin"
            existing.write_bytes(b"keep")
            harness = _Harness(self._permission())
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(existing)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertEqual(existing.read_bytes(), b"keep")
            self.assertEqual(harness.handle.click_calls, 0)

            missing_parent = Path(tmp) / "missing" / "x.bin"
            harness = _Harness(self._permission())
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(missing_parent)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertEqual(harness.handle.click_calls, 0)

            for filename in ("../report.bin", "..\\report.bin", ".", "bad\nname"):
                harness = _Harness(self._permission())
                dest = Path(tmp) / ("dest-" + str(abs(hash(filename))))
                _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(dest)}, expected={"suggested_filename_equals": filename})
                self.assertFalse(effect.success)
                self.assertEqual(harness.handle.click_calls, 0)

    def test_concurrent_destination_creation_at_commit_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "race.bin"
            harness = _Harness(self._permission())
            harness.page.download = _Download(harness.page, content=b"ours", suggested="report.bin")
            harness.page.download.after_save = lambda: destination.write_bytes(b"other-process")
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(destination)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertEqual(destination.read_bytes(), b"other-process")

    def test_oversized_download_refuses_and_temp_is_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "large.bin"
            harness = _Harness(self._permission())
            harness.page.download = _Download(
                harness.page,
                content=b"x" * (DEFAULT_MAX_HASH_BYTES + 1),
                suggested="report.bin",
            )
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(destination)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(harness.page.download.saved_path).exists())

    def test_url_change_and_fresh_page_roll_back_only_owned_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "url.bin"
            harness = _Harness(self._permission())
            harness.page.download = _Download(harness.page, content=b"ours", suggested="report.bin")
            harness.page.download.after_save = lambda: setattr(harness.page, "url", "https://example.test/changed")
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(destination)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertFalse(destination.exists())

            destination = Path(tmp) / "popup.bin"
            harness = _Harness(self._permission())
            extra = _Page()
            harness.page.download = _Download(harness.page, content=b"ours", suggested="report.bin")
            harness.page.download.after_save = lambda: harness.context.pages.append(extra)
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(destination)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertFalse(destination.exists())
            self.assertIn(extra, harness.context.pages)

    def test_owned_destination_replaced_before_rollback_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "replace.bin"
            harness = _Harness(self._permission())
            harness.page.download = _Download(harness.page, content=b"ours", suggested="report.bin")

            def replace_then_fail(session, page_id, page, before_url, pages_before, *, label):
                destination.unlink()
                destination.write_bytes(b"replacement")
                raise RuntimeError("forced postcondition failure")

            harness._require_same_page_postcondition = replace_then_fail
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(destination)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertEqual(destination.read_bytes(), b"replacement")

    def test_scene_stale_before_dispatch_refuses_without_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "x.bin"
            harness = _Harness(self._permission())
            harness.fail_revalidate_at = 1
            _, effect = _act(harness, BrowserActionKind.DOWNLOAD_FILE, args={"destination_path": str(destination)}, expected={"suggested_filename_equals": "report.bin"})
            self.assertFalse(effect.success)
            self.assertEqual(harness.handle.click_calls, 0)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
