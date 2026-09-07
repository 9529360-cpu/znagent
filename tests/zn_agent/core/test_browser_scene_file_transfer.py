from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
    BrowserTarget,
    BrowserTargetKind,
)
from zn_agent.core.browser_scene_clear_press import PlaywrightBrowserSceneClearPressMixin
from zn_agent.core.file_identity import observe_file_identity
from zn_agent.core.models import utc_now


class _Info:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FileInput:
    def __init__(self, chooser):
        self.chooser = chooser

    def evaluate(self, script):
        path = self.chooser.path
        if not path:
            return {
                "connected": True,
                "supported": True,
                "multiple": False,
                "count": 0,
                "files": [],
            }
        file_path = Path(path)
        return {
            "connected": True,
            "supported": True,
            "multiple": False,
            "count": 1,
            "files": [
                {
                    "name": file_path.name,
                    "size": file_path.stat().st_size,
                    "type": "application/octet-stream",
                }
            ],
        }


class _Chooser:
    def __init__(self):
        self.path = ""
        self.element = _FileInput(self)

    def set_files(self, path):
        self.path = str(path)


class _Download:
    def __init__(self, suggested_filename="report.txt", content=b"downloaded"):
        self.suggested_filename = suggested_filename
        self.content = content
        self.saved_path = ""
        self.cancel_calls = 0

    def save_as(self, path):
        self.saved_path = str(path)
        Path(path).write_bytes(self.content)

    def cancel(self):
        self.cancel_calls += 1


class _Page:
    def __init__(self):
        self.url = "https://example.com/start"
        self.chooser = _Chooser()
        self.download = _Download()

    def expect_file_chooser(self):
        return _Info(self.chooser)

    def expect_download(self):
        return _Info(self.download)


class _Handle:
    def __init__(self):
        self.click_calls = 0

    def click(self):
        self.click_calls += 1


class _Base:
    def act(self, action, authority):
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            error="delegated",
        )


class _Harness(PlaywrightBrowserSceneClearPressMixin, _Base):
    def __init__(self, permission):
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake",
        )
        self.page = _Page()
        self.handle = _Handle()
        self.invalidated = []
        self.session = SimpleNamespace(
            identity=identity,
            permission=permission,
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
            name="Choose file",
            selector_hint="browser_scene:button",
        )
        self.binding = SimpleNamespace(
            page_id="page-1",
            target=self.target,
            handle=self.handle,
            scene_target=SimpleNamespace(role="button", frame_id="main"),
        )

    def _session(self, session_id):
        return self.session

    def _validate_authority(self, session, action, authority):
        if not authority.permission.allows_action(action.kind):
            raise RuntimeError(f"browser action is not permitted: {action.kind.value}")

    def _scene_action_binding(self, session, target_id, *, page_id="", expected_target=None):
        return self.binding

    def _scene_revalidate_binding(self, session, binding):
        return None

    def _page(self, session, page_id):
        return self.page

    def _scene_failed_mutation(self, session, page_id):
        self.invalidated.append(("failed", page_id))

    def _scene_invalidate_page(self, session_id, page_id):
        self.invalidated.append(("invalidate", page_id))

    def _reconcile_pages(self, session):
        return None

    @staticmethod
    def _url_allowed(url, permission):
        return permission.allows_origin(url)

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


def _act(harness, kind, *, args=None, expected=None):
    action = BrowserAction.create(
        session_id=harness.session.identity.session_id,
        page_id="page-1",
        kind=kind,
        target=harness.target,
        args=args,
        expected=expected,
    )
    authority = BrowserActionAuthority(
        action_id=action.action_id,
        session_id=action.session_id,
        issued_at=utc_now(),
        observation_captured_at=harness.target.observed_at,
        permission=harness.session.permission,
        target_id=harness.target.target_id,
        page_id="page-1",
    )
    return harness.act(action, authority)


class BrowserSceneFileTransferTests(unittest.TestCase):
    def test_upload_requires_exact_source_identity_and_upload_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "secret.txt"
            source.write_text("hello", encoding="utf-8")
            identity = observe_file_identity(source)

            denied = _Harness(BrowserPermissionContext(allow_page_interaction=True))
            evidence = _act(
                denied,
                BrowserActionKind.UPLOAD_FILE,
                args={"source_identity": identity},
            )
            self.assertFalse(evidence.success)
            self.assertIn("not permitted", evidence.error or "")

            harness = _Harness(
                BrowserPermissionContext(
                    allow_page_interaction=True,
                    allow_uploads=True,
                )
            )
            evidence = _act(
                harness,
                BrowserActionKind.UPLOAD_FILE,
                args={"source_identity": identity},
            )
            self.assertTrue(evidence.success, evidence.error)
            self.assertEqual(harness.page.chooser.path, str(source.resolve()))
            self.assertEqual(evidence.data["source_content_sha256"], identity["content_sha256"])
            self.assertTrue(evidence.data["source_identity_unchanged_after"])

    def test_upload_refuses_stale_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.txt"
            source.write_text("before", encoding="utf-8")
            identity = observe_file_identity(source)
            source.write_text("after", encoding="utf-8")
            harness = _Harness(
                BrowserPermissionContext(
                    allow_page_interaction=True,
                    allow_uploads=True,
                )
            )
            evidence = _act(
                harness,
                BrowserActionKind.UPLOAD_FILE,
                args={"source_identity": identity},
            )
            self.assertFalse(evidence.success)
            self.assertIn("stale", evidence.error or "")
            self.assertEqual(harness.handle.click_calls, 0)

    def test_download_requires_download_authority_and_missing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "report.txt"
            denied = _Harness(BrowserPermissionContext(allow_page_interaction=True))
            evidence = _act(
                denied,
                BrowserActionKind.DOWNLOAD_FILE,
                args={"destination_path": str(destination)},
                expected={"suggested_filename_equals": "report.txt"},
            )
            self.assertFalse(evidence.success)
            self.assertIn("not permitted", evidence.error or "")

            destination.write_text("do not overwrite", encoding="utf-8")
            harness = _Harness(
                BrowserPermissionContext(
                    allow_page_interaction=True,
                    allow_downloads=True,
                )
            )
            evidence = _act(
                harness,
                BrowserActionKind.DOWNLOAD_FILE,
                args={"destination_path": str(destination)},
                expected={"suggested_filename_equals": "report.txt"},
            )
            self.assertFalse(evidence.success)
            self.assertIn("refuses to overwrite", evidence.error or "")
            self.assertEqual(destination.read_text(encoding="utf-8"), "do not overwrite")

    def test_download_saves_causal_event_to_new_verified_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "saved-report.txt"
            harness = _Harness(
                BrowserPermissionContext(
                    allow_page_interaction=True,
                    allow_downloads=True,
                )
            )
            harness.page.download = _Download(
                suggested_filename="report.txt",
                content=b"real bytes",
            )
            evidence = _act(
                harness,
                BrowserActionKind.DOWNLOAD_FILE,
                args={"destination_path": str(destination)},
                expected={"suggested_filename_equals": "report.txt"},
            )
            self.assertTrue(evidence.success, evidence.error)
            self.assertEqual(destination.read_bytes(), b"real bytes")
            identity = observe_file_identity(destination)
            self.assertEqual(evidence.data["destination_content_sha256"], identity["content_sha256"])
            self.assertEqual(evidence.data["destination_path"], str(destination.resolve()))

    def test_download_rejects_wrong_suggested_filename_before_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "saved.txt"
            harness = _Harness(
                BrowserPermissionContext(
                    allow_page_interaction=True,
                    allow_downloads=True,
                )
            )
            harness.page.download = _Download(suggested_filename="other.txt")
            evidence = _act(
                harness,
                BrowserActionKind.DOWNLOAD_FILE,
                args={"destination_path": str(destination)},
                expected={"suggested_filename_equals": "report.txt"},
            )
            self.assertFalse(evidence.success)
            self.assertFalse(destination.exists())
            self.assertEqual(harness.page.download.cancel_calls, 1)


if __name__ == "__main__":
    unittest.main()
