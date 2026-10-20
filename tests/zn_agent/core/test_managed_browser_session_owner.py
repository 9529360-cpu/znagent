from __future__ import annotations

"""Q4: browser session ownership (owner) recording.

Covers NEXT-PHASE §6 "profile/session ownership": every managed session must
record the Work/intent that opened it (work_id/root_id + purpose), surface it
in observation metadata, and attribute close/TTL journal entries to it.
Opening a session without an owner fails explicitly.
"""

import time
import unittest

from zn_agent.core.browser import BrowserPermissionContext, BrowserSessionOwner

_OWNER = BrowserSessionOwner(
    work_id="work-test-1", root_id="root-test-1", purpose="test:session-owner"
)

from zn_agent.core.managed_browser import (
    ManagedBrowserError,
    PlaywrightManagedBrowser,
)
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser
from test_managed_browser import _FakeStarter, _FakePlaywright


class BrowserSessionOwnerTests(unittest.TestCase):
    def test_owner_rejects_empty_fields(self):
        for kwargs in (
            {"work_id": "", "root_id": "r", "purpose": "p"},
            {"work_id": "w", "root_id": "  ", "purpose": "p"},
            {"work_id": "w", "root_id": "r", "purpose": ""},
        ):
            with self.assertRaises(ValueError):
                BrowserSessionOwner(**kwargs)

    def test_owner_as_dict(self):
        self.assertEqual(
            _OWNER.as_dict(),
            {
                "work_id": "work-test-1",
                "root_id": "root-test-1",
                "purpose": "test:session-owner",
            },
        )


class ManagedBrowserSessionOwnerTests(unittest.TestCase):
    def _build(self, **kwargs):
        playwright = _FakePlaywright()
        adapter = PlaywrightManagedBrowser(
            playwright_factory=lambda: _FakeStarter(playwright),
            url_checker=lambda url, **kwargs: True,
            **kwargs,
        )
        return adapter, playwright

    def test_open_session_without_owner_fails_explicitly(self):
        adapter, _ = self._build()
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "owner"):
                adapter.open_session(
                    permission=BrowserPermissionContext(), headless=True
                )
            # No half-opened session may linger after the explicit failure.
            self.assertEqual(adapter._sessions, {})
        finally:
            adapter.close()

    def test_open_session_with_non_owner_object_fails_explicitly(self):
        adapter, _ = self._build()
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "owner"):
                adapter.open_session(
                    permission=BrowserPermissionContext(),
                    headless=True,
                    owner={"work_id": "w", "root_id": "r", "purpose": "p"},
                )
            self.assertEqual(adapter._sessions, {})
        finally:
            adapter.close()

    def test_open_session_records_owner_on_session(self):
        adapter, _ = self._build()
        try:
            identity = adapter.open_session(
                permission=BrowserPermissionContext(), headless=True, owner=_OWNER
            )
            session = adapter._sessions[identity.session_id]
            self.assertEqual(session.owner, _OWNER)
        finally:
            adapter.close()

    def test_observation_metadata_carries_owner(self):
        adapter, _ = self._build()
        try:
            identity = adapter.open_session(
                permission=BrowserPermissionContext(
                    allow_navigation=True, allow_page_interaction=True
                ),
                headless=True,
                owner=_OWNER,
            )
            observation = adapter.observe(identity.session_id)
            self.assertEqual(observation.metadata["owner"], _OWNER.as_dict())
        finally:
            adapter.close()

    def test_explicit_close_journal_carries_owner(self):
        adapter, _ = self._build()
        try:
            identity = adapter.open_session(
                permission=BrowserPermissionContext(), headless=True, owner=_OWNER
            )
            adapter.close_session(identity.session_id)
            events = adapter.session_events()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["reason"], "explicit")
            self.assertEqual(events[0]["owner"], _OWNER.as_dict())
        finally:
            adapter.close()

    def test_ttl_close_journal_carries_owner(self):
        adapter, _ = self._build(session_idle_ttl_seconds=60)
        try:
            identity = adapter.open_session(
                permission=BrowserPermissionContext(), headless=True, owner=_OWNER
            )
            session = adapter._sessions[identity.session_id]
            session.last_activity_monotonic = time.monotonic() - 61
            closed = adapter.close_idle_sessions()
            self.assertEqual(closed, [identity.session_id])
            events = adapter.session_events()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["reason"], "idle_ttl")
            self.assertEqual(events[0]["owner"], _OWNER.as_dict())
        finally:
            adapter.close()

    def test_semantic_browser_open_without_owner_fails_explicitly(self):
        # The file-transfer mixin overrides open_session on the product path;
        # the owner requirement must hold there too.
        playwright = _FakePlaywright()
        adapter = SemanticPlaywrightManagedBrowser(
            playwright_factory=lambda: _FakeStarter(playwright),
            url_checker=lambda url, **kwargs: True,
        )
        try:
            with self.assertRaisesRegex(ManagedBrowserError, "owner"):
                adapter.open_session(
                    permission=BrowserPermissionContext(
                        allow_page_interaction=True, allow_downloads=True
                    ),
                    headless=True,
                )
            self.assertEqual(adapter._sessions, {})
        finally:
            adapter.close()

    def test_semantic_browser_file_transfer_session_carries_owner(self):
        playwright = _FakePlaywright()
        adapter = SemanticPlaywrightManagedBrowser(
            playwright_factory=lambda: _FakeStarter(playwright),
            url_checker=lambda url, **kwargs: True,
        )
        try:
            identity = adapter.open_session(
                permission=BrowserPermissionContext(
                    allow_page_interaction=True, allow_downloads=True
                ),
                headless=True,
                owner=_OWNER,
            )
            observation = adapter.observe(identity.session_id)
            self.assertEqual(observation.metadata["owner"], _OWNER.as_dict())
        finally:
            adapter.close()


if __name__ == "__main__":
    unittest.main()
