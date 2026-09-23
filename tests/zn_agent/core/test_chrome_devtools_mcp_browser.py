from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
    BrowserTargetRegroundDisposition,
)
from zn_agent.core.chrome_devtools_mcp_browser import (
    CHROME_DEVTOOLS_MCP_PROVIDER,
    ChromeDevToolsMcpBrowserUnavailable,
    ChromeDevToolsMcpManagedBrowser,
    resolve_chrome_devtools_mcp_command,
)
from zn_agent.core.stdio_mcp import StdioMcpCommand


class _FakeChromeMcpClient:
    def __init__(self, **_kwargs):
        self.url = "about:blank"
        self.title = ""
        self.text_value = ""
        self.node_generation = 0
        self.closed = False

    def start(self):
        return self

    def close(self):
        self.closed = True

    def call_tool(self, name, arguments=None):
        args = dict(arguments or {})
        if name == "list_pages":
            return {
                "structuredContent": {
                    "pages": [
                        {
                            "id": 1,
                            "url": self.url,
                            "title": self.title,
                            "selected": True,
                        }
                    ]
                }
            }
        if name == "take_snapshot":
            return {
                "structuredContent": {
                    "snapshot": {
                        "id": "1_0",
                        "role": "RootWebArea",
                        "name": self.title or "test",
                        "url": self.url,
                        "children": [
                            {
                                "id": f"{1 + self.node_generation}_1",
                                "role": "textbox",
                                "name": "Search",
                                "value": self.text_value,
                            },
                            {
                                "id": f"{1 + self.node_generation}_2",
                                "role": "button",
                                "name": "Submit",
                            },
                        ],
                    }
                }
            }
        if name == "navigate_page":
            self.url = str(args.get("url") or self.url)
            self.title = "Example"
            return {"structuredContent": {"message": "navigated"}}
        if name == "fill":
            if args.get("uid") == "1_1":
                self.text_value = str(args.get("value") or "")
            return {"structuredContent": {}}
        if name == "click":
            if args.get("uid") == "1_2":
                self.url = "https://example.test/done"
            return {"structuredContent": {}}
        if name == "evaluate_script":
            fence = chr(96) * 3
            function = str(args.get("function") or "")
            value = (
                {
                    "connected": True,
                    "sensitive": False,
                    "disabled": False,
                    "read_only": False,
                    "checked": None,
                    "focused": False,
                    "value": self.text_value,
                    "selected_text": "",
                }
                if "selected_text" in function
                else True
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Script ran on page and returned:\n"
                            + fence
                            + "json\n"
                            + __import__("json").dumps(value)
                            + "\n"
                            + fence
                        ),
                    }
                ]
            }
        if name in {"press_key", "wait_for", "select_page"}:
            return {"structuredContent": {}}
        raise AssertionError(f"unexpected tool: {name}")


def _command_factory(**_kwargs):
    return StdioMcpCommand(
        argv=("node", "fake"),
        cwd=Path("."),
        env={},
    )


class ChromeDevToolsMcpManagedBrowserTests(unittest.TestCase):
    def _browser(self):
        return ChromeDevToolsMcpManagedBrowser(
            client_factory=_FakeChromeMcpClient,
            command_factory=_command_factory,
            url_checker=lambda *_args, **_kwargs: True,
        )

    def _permission(self):
        return BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_text_entry=True,
            allowed_origins=("https://example.test",),
        )

    def test_navigation_and_semantic_form_actions_keep_zn_authority(self):
        browser = self._browser()
        permission = self._permission()
        session = browser.open_session(permission=permission, headless=True)
        try:
            initial = browser.observe(session.session_id)
            navigate = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.NAVIGATE,
                page_id=initial.page_id,
                args={"url": "https://example.test/start"},
                expected={"url_equals": "https://example.test/start"},
            )
            effect = browser.act(
                navigate,
                BrowserActionAuthority.from_observation(
                    navigate, initial, permission
                ),
            )
            self.assertTrue(effect.success)
            self.assertEqual(effect.postcondition, "safe_current_page_observed")
            self.assertEqual(effect.data["provider"], CHROME_DEVTOOLS_MCP_PROVIDER)
            self.assertEqual(effect.data["provider"], "chrome-devtools-mcp@1.9.0")

            textbox = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                    value="Search",
                ),
                page_id=effect.page_id,
            )
            type_action = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.TYPE_TEXT,
                page_id=textbox.page_id,
                target=textbox.target,
                args={"text": "mature browser"},
            )
            typed = browser.act(
                type_action,
                BrowserActionAuthority.from_observation(
                    type_action, textbox, permission
                ),
            )
            self.assertTrue(typed.success)
            self.assertTrue(typed.data["exact_node_continuity"])
            self.assertEqual(typed.data["text_length_after"], len("mature browser"))

            button = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
                    value="Submit",
                ),
                page_id=typed.page_id,
            )
            click = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.CLICK,
                page_id=button.page_id,
                target=button.target,
                expected={"url_equals": "https://example.test/done"},
            )
            clicked = browser.act(
                click,
                BrowserActionAuthority.from_observation(
                    click, button, permission
                ),
            )
            self.assertTrue(clicked.success)
            self.assertEqual(clicked.url_after, "https://example.test/done")
        finally:
            browser.close()
        self.assertEqual(browser._sessions, {})

    def test_semantic_target_reground_uses_fresh_provider_uid_for_continuity(self):
        browser = self._browser()
        permission = self._permission()
        session = browser.open_session(permission=permission, headless=True)
        query = BrowserTargetQuery(
            kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
            value="Submit",
        )
        try:
            initial = browser.observe(session.session_id)
            navigate = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.NAVIGATE,
                page_id=initial.page_id,
                args={"url": "https://example.test/start"},
                expected={"url_equals": "https://example.test/start"},
            )
            moved = browser.act(
                navigate,
                BrowserActionAuthority.from_observation(
                    navigate,
                    initial,
                    permission,
                ),
            )
            self.assertTrue(moved.success, moved.error)
            observed = browser.observe_target(
                session.session_id,
                query,
                page_id=moved.page_id,
            )
            assert observed.target is not None

            same = browser.reground_target(
                session.session_id,
                query,
                observed.target,
                page_id=observed.page_id,
            )
            self.assertIs(
                same.disposition,
                BrowserTargetRegroundDisposition.SAME_EXACT_TARGET,
            )

            browser._sessions[session.session_id].client.node_generation += 1
            rebound = browser.reground_target(
                session.session_id,
                query,
                observed.target,
                page_id=observed.page_id,
            )
            self.assertIs(
                rebound.disposition,
                BrowserTargetRegroundDisposition.REBOUND_TARGET,
            )
            self.assertFalse(rebound.exact_node_continuity)
        finally:
            browser.close()

    def test_command_uses_pinned_runtime_real_chrome_and_privacy_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "node_modules" / "chrome-devtools-mcp"
            server = package / "build" / "src" / "bin" / "chrome-devtools-mcp.js"
            server.parent.mkdir(parents=True)
            server.write_text("// fixture\n", encoding="utf-8")
            (package / "package.json").write_text(
                '{"name":"chrome-devtools-mcp","version":"1.9.0"}',
                encoding="utf-8",
            )
            node = root / "node.exe"
            chrome = root / "chrome.exe"
            playwright_chromium = root / "playwright-chromium.exe"
            node.write_text("fixture", encoding="utf-8")
            chrome.write_text("fixture", encoding="utf-8")
            playwright_chromium.write_text("fixture", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "ZN_CHROME_DEVTOOLS_MCP_ROOT": str(root),
                    "ZN_NODE_EXECUTABLE": str(node),
                    "ZN_BROWSER_EXECUTABLE": str(playwright_chromium),
                    "ZN_CHROME_EXECUTABLE": str(chrome),
                },
                clear=False,
            ):
                command = resolve_chrome_devtools_mcp_command(
                    headless=True,
                    permission=self._permission(),
                )

            self.assertTrue(os.path.samefile(command.argv[0], node))
            self.assertTrue(os.path.samefile(command.argv[1], server))
            self.assertIn("--experimental-structured-content=true", command.argv)
            self.assertIn("--no-usage-statistics", command.argv)
            self.assertIn("--no-performance-crux", command.argv)
            self.assertIn("--redact-network-headers=true", command.argv)
            self.assertIn("--executable-path", command.argv)
            chrome_arg = command.argv[command.argv.index("--executable-path") + 1]
            self.assertTrue(os.path.samefile(chrome_arg, chrome))
            self.assertFalse(os.path.samefile(chrome_arg, playwright_chromium))
            self.assertNotIn("chrome-devtools-mcp@latest", " ".join(command.argv))

    def test_file_transfer_permission_fails_before_provider_start(self):
        browser = ChromeDevToolsMcpManagedBrowser()
        with self.assertRaisesRegex(
            ChromeDevToolsMcpBrowserUnavailable,
            "causal file-transfer contract",
        ):
            browser.open_session(
                permission=BrowserPermissionContext(
                    allow_page_interaction=True,
                    allow_downloads=True,
                )
            )

    def test_command_rejects_unpinned_runtime_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "node_modules" / "chrome-devtools-mcp"
            server = package / "build" / "src" / "bin" / "chrome-devtools-mcp.js"
            server.parent.mkdir(parents=True)
            server.write_text("// fixture\n", encoding="utf-8")
            (package / "package.json").write_text(
                '{"name":"chrome-devtools-mcp","version":"9.9.9"}',
                encoding="utf-8",
            )
            node = root / "node.exe"
            chrome = root / "chrome.exe"
            node.write_text("fixture", encoding="utf-8")
            chrome.write_text("fixture", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "ZN_CHROME_DEVTOOLS_MCP_ROOT": str(root),
                    "ZN_NODE_EXECUTABLE": str(node),
                    "ZN_BROWSER_EXECUTABLE": str(chrome),
                },
                clear=False,
            ):
                with self.assertRaisesRegex(
                    ChromeDevToolsMcpBrowserUnavailable,
                    "version mismatch",
                ):
                    resolve_chrome_devtools_mcp_command(
                        headless=True,
                        permission=self._permission(),
                    )

    def test_stale_authority_is_rejected_before_provider_dispatch(self):
        browser = self._browser()
        permission = self._permission()
        session = browser.open_session(permission=permission, headless=True)
        initial = browser.observe(session.session_id)
        action = BrowserAction.create(
            session_id=session.session_id,
            kind=BrowserActionKind.NAVIGATE,
            page_id=initial.page_id,
            args={"url": "https://example.test/start"},
        )
        authority = BrowserActionAuthority.from_observation(
            action, initial, permission
        )
        browser.observe(session.session_id)
        effect = browser.act(action, authority)
        self.assertFalse(effect.success)
        self.assertIn("stale", str(effect.error).casefold())
        browser.close()


if __name__ == "__main__":
    unittest.main()
