from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from zn_agent.core.browser import (
    BrowserActionAuthority,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
)
from zn_agent.core.browser_rpc import BrowserResidentRpcServer
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class _FakeManagedBrowser:
    def __init__(self) -> None:
        self.sessions: dict[str, BrowserPermissionContext] = {}
        self.closed: set[str] = set()
        self.last_action = None
        self.call_threads: list[int] = []

    def _record_thread(self) -> None:
        self.call_threads.append(threading.get_ident())

    def open_session(self, *, permission=None, headless=True):
        self._record_thread()
        assert headless is True
        policy = permission or BrowserPermissionContext()
        session = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider="fake-chromium",
            browser_name="chromium",
        )
        self.sessions[session.session_id] = policy
        return session

    def observe(self, session_id: str, *, page_id: str = ""):
        self._record_thread()
        if session_id not in self.sessions or session_id in self.closed:
            raise ValueError("unknown fake session")
        session = BrowserSessionIdentity(
            session_id=session_id,
            plane=BrowserPlane.MANAGED,
            provider="fake-chromium",
            browser_name="chromium",
        )
        return BrowserObservation(
            session=session,
            page_id=page_id or "page-1",
            captured_at=utc_now(),
            url="about:blank",
            title="",
            load_state="complete",
        )

    def act(self, action, authority: BrowserActionAuthority):
        self._record_thread()
        observation = BrowserObservation(
            session=BrowserSessionIdentity(
                session_id=action.session_id,
                plane=BrowserPlane.MANAGED,
                provider="fake-chromium",
                browser_name="chromium",
            ),
            page_id=action.page_id,
            captured_at=authority.observation_captured_at,
            url="about:blank",
            title="",
            load_state="complete",
        )
        authority.validate_current(action, observation, self.sessions[action.session_id])
        self.last_action = action
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=action.page_id,
            url_before="about:blank",
            url_after=str(action.args["url"]),
            postcondition="safe_current_page_observed",
        )

    def close_session(self, session_id: str) -> None:
        self._record_thread()
        self.closed.add(session_id)

    def close(self) -> None:
        self._record_thread()
        self.closed.update(self.sessions)


class ResidentBrowserRpcTests(unittest.TestCase):
    def _server(self, root: Path):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        browser = _FakeManagedBrowser()
        resident.managed_browser = browser
        return BrowserResidentRpcServer(resident=resident), browser

    @staticmethod
    def _close(server: BrowserResidentRpcServer) -> None:
        try:
            server.resident.managed_browser.close()
        finally:
            server.resident.store.close()

    def test_formal_browser_rpc_status_identifies_surface_but_plain_server_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server, _ = self._server(root)
            try:
                status = server.handle({"id": "formal", "method": "status", "params": {}})
                self.assertEqual(
                    status["result"]["resident_surface"],
                    {"name": "zn-formal-resident", "schema": 2},
                )
            finally:
                self._close(server)

        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            server = ResidentRpcServer(resident=resident)
            try:
                status = server.handle({"id": "plain", "method": "status", "params": {}})
                self.assertNotIn("resident_surface", status["result"])
            finally:
                resident.store.close()

    def test_browser_rpc_defaults_to_observation_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server, browser = self._server(Path(tmp))
            try:
                opened = server.handle({"id": "open", "method": "browser_open", "params": {}})
                self.assertTrue(opened["ok"])
                session_id = opened["result"]["session_id"]
                observed = server.handle(
                    {
                        "id": "observe",
                        "method": "browser_observe",
                        "params": {"session_id": session_id},
                    }
                )
                self.assertEqual(observed["result"]["session"]["plane"], "managed")
                with self.assertRaisesRegex(ValueError, "not permitted"):
                    server.handle(
                        {
                            "id": "navigate",
                            "method": "browser_navigate",
                            "params": {"session_id": session_id, "url": "https://example.com/"},
                        }
                    )
                self.assertIsNone(browser.last_action)
            finally:
                self._close(server)
            self.assertEqual(len(set(browser.call_threads)), 1)

    def test_browser_rpc_navigation_and_cleanup_stay_on_one_resident_owner_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server, browser = self._server(Path(tmp))
            try:
                opened = server.handle(
                    {
                        "id": "open",
                        "method": "browser_open",
                        "params": {
                            "permission": {
                                "allow_navigation": True,
                                "allowed_origins": ["https://example.com"],
                            }
                        },
                    }
                )
                session_id = opened["result"]["session_id"]
                navigated = server.handle(
                    {
                        "id": "navigate",
                        "method": "browser_navigate",
                        "params": {
                            "session_id": session_id,
                            "url": "https://example.com/",
                            "url_equals": "https://example.com/",
                        },
                    }
                )
                self.assertTrue(navigated["ok"])
                self.assertTrue(navigated["result"]["success"])
                self.assertEqual(navigated["result"]["url_after"], "https://example.com/")
                self.assertIsNotNone(browser.last_action)
                self.assertEqual(browser.last_action.args["url"], "https://example.com/")

                closed = server.handle(
                    {
                        "id": "close",
                        "method": "browser_close",
                        "params": {"session_id": session_id},
                    }
                )
                self.assertTrue(closed["result"]["closed"])
                with self.assertRaisesRegex(ValueError, "unknown resident managed-browser session"):
                    server.handle(
                        {
                            "id": "observe-again",
                            "method": "browser_observe",
                            "params": {"session_id": session_id},
                        }
                    )
                ping = server.handle({"id": "ping", "method": "ping", "params": {}})
                self.assertTrue(ping["result"]["alive"])
            finally:
                self._close(server)
            self.assertGreaterEqual(len(browser.call_threads), 5)
            self.assertEqual(len(set(browser.call_threads)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
