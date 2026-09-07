from __future__ import annotations

import hashlib
import http.server
import tempfile
import threading
import unittest
from pathlib import Path

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from zn_agent.core.file_identity import compare_file_identities, observe_file_identity
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser


_DOWNLOAD_BYTES = b"ZN causal download fixture\x00with exact bytes\n"
_DOWNLOAD_NAME = "fixture-download.bin"


class _FileTransferFixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/download"):
            payload = _DOWNLOAD_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{_DOWNLOAD_NAME}"',
            )
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        payload = b"""<!doctype html><html><head><title>ZN File Transfer</title></head>
        <body><main>
          <h1>File transfer fixture</h1>
          <input id='file-input' type='file' hidden
            onchange="document.getElementById('upload-status').textContent =
              this.files.length === 1 ? this.files[0].name + ':' + this.files[0].size : 'none'">
          <button aria-label='Choose exact file'
            onclick="document.getElementById('file-input').click()">Choose exact file</button>
          <div id='upload-status'>none</div>
          <a aria-label='Download exact file' href='/download'>Download exact file</a>
        </main></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserFileTransferWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            _FileTransferFixtureHandler,
        )
        cls.port = int(cls.server.server_address[1])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _navigate(self, browser, identity, permission, page_id):
        initial = browser.observe(identity.session_id, page_id=page_id)
        page_url = self.origin + "/fixture"
        action = BrowserAction.create(
            session_id=identity.session_id,
            page_id=page_id,
            kind=BrowserActionKind.NAVIGATE,
            args={"url": page_url},
            expected={"url_equals": page_url},
        )
        effect = browser.act(
            action,
            BrowserActionAuthority.from_observation(action, initial, permission),
        )
        self.assertTrue(effect.success, effect.error)
        return page_url

    @staticmethod
    def _scene_action(browser, identity, permission, *, page_id, role, name, kind, args, expected):
        scene = browser.observe_scene(identity.session_id, page_id=page_id)
        target = next(
            item
            for item in scene.targets
            if item.role == role and item.accessible_name == name
        )
        observed = browser.observe_scene_target(
            identity.session_id,
            target.target_id,
            page_id=page_id,
        )
        action = BrowserAction.create(
            session_id=identity.session_id,
            page_id=page_id,
            kind=kind,
            target=observed.target,
            args=args,
            expected=expected,
        )
        authority = BrowserActionAuthority.from_observation(action, observed, permission)
        return browser.act(action, authority)

    def test_real_chromium_causal_upload_and_download_round_trip(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_uploads=True,
            allow_downloads=True,
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = SemanticPlaywrightManagedBrowser()
        identity = browser.open_session(permission=permission, headless=True)
        try:
            page_id = browser.observe(identity.session_id).page_id
            page_url = self._navigate(browser, identity, permission, page_id)
            provider_page = browser._sessions[identity.session_id].pages[page_id]

            with tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "upload-fixture.txt"
                source.write_bytes(b"known upload bytes")
                source_identity = observe_file_identity(source)

                upload = self._scene_action(
                    browser,
                    identity,
                    permission,
                    page_id=page_id,
                    role="button",
                    name="Choose exact file",
                    kind=BrowserActionKind.UPLOAD_FILE,
                    args={"source_identity": source_identity},
                    expected={},
                )
                self.assertTrue(upload.success, upload.error)
                self.assertEqual(upload.url_before, page_url)
                self.assertEqual(upload.url_after, page_url)
                self.assertEqual(upload.data["source_sha256"], source_identity["content_sha256"])
                self.assertEqual(upload.data["source_size"], source_identity["size_bytes"])
                self.assertTrue(upload.data["source_identity_unchanged_after"])
                self.assertEqual(
                    provider_page.locator("#upload-status").text_content(),
                    f"{source.name}:{source.stat().st_size}",
                )
                dom_file = provider_page.locator("#file-input").evaluate(
                    "element => ({count: element.files.length, name: element.files[0]?.name || '', size: element.files[0]?.size || -1})"
                )
                self.assertEqual(dom_file["count"], 1)
                self.assertEqual(dom_file["name"], source.name)
                self.assertEqual(dom_file["size"], source.stat().st_size)
                source_after = observe_file_identity(source)
                self.assertTrue(compare_file_identities(source_identity, source_after)["exact"])

                destination = Path(tmp) / "downloaded.bin"
                download = self._scene_action(
                    browser,
                    identity,
                    permission,
                    page_id=page_id,
                    role="link",
                    name="Download exact file",
                    kind=BrowserActionKind.DOWNLOAD_FILE,
                    args={"destination_path": str(destination)},
                    expected={"suggested_filename_equals": _DOWNLOAD_NAME},
                )
                self.assertTrue(download.success, download.error)
                self.assertEqual(download.url_before, page_url)
                self.assertEqual(download.url_after, page_url)
                self.assertEqual(destination.read_bytes(), _DOWNLOAD_BYTES)
                expected_hash = hashlib.sha256(_DOWNLOAD_BYTES).hexdigest()
                final_identity = observe_file_identity(destination)
                self.assertTrue(final_identity["digest_complete"])
                self.assertEqual(final_identity["content_sha256"], expected_hash)
                self.assertEqual(download.data["download_sha256"], expected_hash)
                self.assertEqual(download.data["download_size"], len(_DOWNLOAD_BYTES))
                self.assertTrue(download.data["exclusive_create_commit"])
                self.assertTrue(download.data["temp_sha256_matches_final"])
                self.assertEqual(browser.observe(identity.session_id, page_id=page_id).url, page_url)
        finally:
            browser.close_session(identity.session_id)

    def test_real_chromium_wrong_suggested_filename_creates_no_destination(self):
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_downloads=True,
            allow_private_network=True,
            allowed_origins=(self.origin,),
        )
        browser = SemanticPlaywrightManagedBrowser()
        identity = browser.open_session(permission=permission, headless=True)
        try:
            page_id = browser.observe(identity.session_id).page_id
            self._navigate(browser, identity, permission, page_id)
            with tempfile.TemporaryDirectory() as tmp:
                destination = Path(tmp) / "must-not-exist.bin"
                effect = self._scene_action(
                    browser,
                    identity,
                    permission,
                    page_id=page_id,
                    role="link",
                    name="Download exact file",
                    kind=BrowserActionKind.DOWNLOAD_FILE,
                    args={"destination_path": str(destination)},
                    expected={"suggested_filename_equals": "wrong-name.bin"},
                )
                self.assertFalse(effect.success)
                self.assertIn("suggested_filename", effect.error or "")
                self.assertFalse(destination.exists())
        finally:
            browser.close_session(identity.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
