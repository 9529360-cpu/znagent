"""Q5 action-dispatch audit: PRESS / WAIT handlers on the managed browser.

Covers the two BrowserActionKind values that previously fell through to the
"not implemented yet" branch of PlaywrightManagedBrowser.act, plus a
dispatch-completeness audit that walks all 20 declared kinds through the
product path (SemanticPlaywrightManagedBrowser) and proves none of them hits
the "not implemented" fallback.
"""

from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserSessionOwner,
    BrowserTarget,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.managed_browser import PlaywrightManagedBrowser
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser

_OWNER = BrowserSessionOwner(work_id="test", root_id="test", purpose="test")


class _FakeHandle:
    """Minimal element handle: evidence dict + focus, for binding injection."""

    def __init__(self, dom_id):
        self.dom_id = dom_id
        self.focused = False
        self.disposed = False

    def evaluate(self, expression, arg=None):
        return {
            "count": 1,
            "current": True,
            "connected": True,
            "visible": True,
            "dom_id": self.dom_id,
            "tag": "input",
            "role": "textbox",
            "name": "Search",
            "input_type": "text",
            "is_password": False,
        }

    def focus(self):
        self.focused = True

    def dispose(self):
        self.disposed = True


class _FakeKeyboard:
    def __init__(self):
        self.press_calls = []

    def press(self, key):
        self.press_calls.append(key)


class _FakePage:
    def __init__(self, url="about:blank"):
        self.url = url
        self.inner_text = ""
        self.keyboard = _FakeKeyboard()
        self.wait_calls = []
        self.goto_calls = []
        self.history_calls = []
        self.closed = False
        self.viewport_size = {"width": 1280, "height": 720}

    def title(self):
        return "Fixture"

    def evaluate(self, expression, arg=None):
        if expression == "document.readyState" and arg is None:
            return "complete"
        raise AssertionError(f"unexpected page evaluate expression: {expression!r}")

    def wait_for_function(self, expression, *, arg=None, timeout=None):
        self.wait_calls.append((expression, arg, timeout))
        texts = [str(item) for item in (arg or []) if str(item)]
        if any(text and text in self.inner_text for text in texts):
            return {"matched": True}
        raise TimeoutError(f"Timeout {timeout}ms exceeded.")

    def goto(self, url, *, wait_until):
        self.goto_calls.append((url, wait_until))
        self.url = url

    def go_back(self, *, wait_until=None):
        self.history_calls.append("back")
        return True

    def go_forward(self, *, wait_until=None):
        self.history_calls.append("forward")
        return True

    def reload(self, *, wait_until=None):
        self.history_calls.append("reload")

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()
        self.pages = [self.page]
        self._handed_out = False
        self.closed = False

    def set_default_navigation_timeout(self, value):
        pass

    def set_default_timeout(self, value):
        pass

    def route(self, pattern, handler):
        pass

    def new_page(self):
        if not self._handed_out:
            self._handed_out = True
            return self.page
        page = _FakePage()
        self.pages.append(page)
        return page

    def close(self):
        self.closed = True


class _FakeBrowser:
    version = "fake-1"

    def __init__(self):
        self.context = _FakeContext()

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        pass


class _FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    def launch(self, *, headless):
        return self.browser


class _FakePlaywright:
    def __init__(self):
        self.browser = _FakeBrowser()
        self.chromium = _FakeChromium(self.browser)

    def stop(self):
        pass


class _FakeStarter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def _permission(**overrides):
    base = {
        "allow_navigation": True,
        "allow_page_interaction": True,
        "allow_text_entry": True,
    }
    base.update(overrides)
    return BrowserPermissionContext(**base)


def _build(adapter_cls=PlaywrightManagedBrowser, *, permission=None):
    playwright = _FakePlaywright()
    adapter = adapter_cls(
        playwright_factory=lambda: _FakeStarter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    identity = adapter.open_session(
        owner=_OWNER,
        permission=permission or _permission(),
        headless=True,
    )
    return adapter, playwright, identity


def _act(adapter, identity, permission, *, kind, args=None, expected=None, page_id=""):
    observation = adapter.observe(identity.session_id, page_id=page_id)
    action = BrowserAction.create(
        session_id=identity.session_id,
        page_id=page_id,
        kind=kind,
        args=args,
        expected=expected,
    )
    authority = BrowserActionAuthority.from_observation(action, observation, permission)
    return adapter.act(action, authority)


class PressTests(unittest.TestCase):
    def test_press_dispatches_key_and_returns_fresh_postcondition(self):
        permission = _permission()
        adapter, playwright, identity = _build(permission=permission)
        page = playwright.browser.context.page
        page.url = "https://example.com/form"
        try:
            effect = _act(
                adapter,
                identity,
                permission,
                kind=BrowserActionKind.PRESS,
                args={"key": "Enter"},
            )
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "fresh_post_key_observation")
            self.assertEqual(effect.data["key"], "Enter")
            self.assertEqual(page.keyboard.press_calls, ["Enter"])
        finally:
            adapter.close()

    def test_press_requires_non_empty_key(self):
        permission = _permission()
        adapter, _playwright, identity = _build(permission=permission)
        try:
            effect = _act(
                adapter,
                identity,
                permission,
                kind=BrowserActionKind.PRESS,
                args={"key": "   "},
            )
            self.assertFalse(effect.success)
            self.assertIn("non-empty args.key", effect.error or "")
        finally:
            adapter.close()

    def test_press_rejects_extra_args_keys(self):
        permission = _permission()
        adapter, _playwright, identity = _build(permission=permission)
        try:
            effect = _act(
                adapter,
                identity,
                permission,
                kind=BrowserActionKind.PRESS,
                args={"key": "Enter", "target": "x"},
            )
            self.assertFalse(effect.success)
            self.assertIn("exactly {key}", effect.error or "")
        finally:
            adapter.close()

    def test_press_url_equals_postcondition_is_checked(self):
        permission = _permission()
        adapter, playwright, identity = _build(permission=permission)
        page = playwright.browser.context.page
        page.url = "https://example.com/before"
        try:
            effect = _act(
                adapter,
                identity,
                permission,
                kind=BrowserActionKind.PRESS,
                args={"key": "Tab"},
                expected={"url_equals": "https://example.com/after"},
            )
            self.assertFalse(effect.success)
            self.assertEqual(effect.postcondition, "url_equals")
            self.assertIn("did not match observed URL", effect.error or "")
        finally:
            adapter.close()

    def test_press_with_target_focuses_exact_node_first(self):
        import dataclasses

        from zn_agent.core.managed_browser import _ManagedTargetBinding

        permission = _permission()
        adapter, playwright, identity = _build(permission=permission)
        page = playwright.browser.context.page
        page.url = "https://example.com/form"
        try:
            observation = adapter.observe(identity.session_id)
            query = BrowserTargetQuery(
                kind=BrowserTargetQueryKind.DOM_ID, value="search-input"
            )
            handle = _FakeHandle("search-input")
            target = adapter._target_from_evidence(
                adapter._sessions[identity.session_id],
                observation.page_id,
                query,
                handle.evaluate("evidence", query.value),
                observed_at=observation.captured_at,
            )
            session = adapter._sessions[identity.session_id]
            session.target_bindings[observation.page_id] = _ManagedTargetBinding(
                target=target, query=query, handle=handle
            )
            session.last_observation[observation.page_id] = dataclasses.replace(
                observation, target=target
            )
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserActionKind.PRESS,
                target=target,
                args={"key": "Enter"},
            )
            authority = BrowserActionAuthority.from_observation(
                action, session.last_observation[observation.page_id], permission
            )
            effect = adapter.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertTrue(handle.focused)
            self.assertEqual(page.keyboard.press_calls, ["Enter"])
            self.assertEqual(effect.target_id, target.target_id)
        finally:
            adapter.close()

    def test_press_is_rejected_without_page_interaction_permission(self):
        permission = _permission(allow_page_interaction=False)
        adapter, _playwright, identity = _build(permission=permission)
        page_observation = adapter.observe(identity.session_id)
        action = BrowserAction.create(
            session_id=identity.session_id,
            kind=BrowserActionKind.PRESS,
            args={"key": "Enter"},
        )
        try:
            with self.assertRaisesRegex(ValueError, "not permitted"):
                BrowserActionAuthority.from_observation(
                    action, page_observation, permission
                )
        finally:
            adapter.close()


class WaitTests(unittest.TestCase):
    def test_wait_succeeds_when_text_is_present(self):
        permission = _permission()
        adapter, playwright, identity = _build(permission=permission)
        page = playwright.browser.context.page
        page.url = "https://example.com/status"
        page.inner_text = "order confirmed, thank you"
        try:
            effect = _act(
                adapter,
                identity,
                permission,
                kind=BrowserActionKind.WAIT,
                args={"text": ["confirmed", "missing"], "timeout_ms": 5000},
            )
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "wait_condition_observed")
            expression, arg, timeout = page.wait_calls[0]
            self.assertEqual(arg, ["confirmed", "missing"])
            self.assertEqual(timeout, 5000)
        finally:
            adapter.close()

    def test_wait_timeout_is_failed_evidence_not_an_exception(self):
        permission = _permission()
        adapter, playwright, identity = _build(permission=permission)
        page = playwright.browser.context.page
        page.inner_text = "nothing relevant here"
        try:
            effect = _act(
                adapter,
                identity,
                permission,
                kind=BrowserActionKind.WAIT,
                args={"text": "confirmed", "timeout_ms": 100},
            )
            self.assertFalse(effect.success)
            self.assertIn("not observed within", effect.error or "")
        finally:
            adapter.close()

    def test_wait_default_timeout_is_15s(self):
        permission = _permission()
        adapter, playwright, identity = _build(permission=permission)
        page = playwright.browser.context.page
        page.inner_text = "confirmed"
        try:
            effect = _act(
                adapter,
                identity,
                permission,
                kind=BrowserActionKind.WAIT,
                args={"text": "confirmed"},
            )
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(page.wait_calls[0][2], 15_000)
        finally:
            adapter.close()

    def test_wait_rejects_unbounded_or_empty_shape(self):
        permission = _permission()
        adapter, _playwright, identity = _build(permission=permission)
        try:
            for args in (
                {"text": "x", "timeout_ms": 99},
                {"text": "x", "timeout_ms": 60_001},
                {"text": "   "},
                {"text": []},
                {"text": "x", "timeout_ms": 1000, "extra": 1},
            ):
                effect = _act(
                    adapter,
                    identity,
                    permission,
                    kind=BrowserActionKind.WAIT,
                    args=args,
                )
                self.assertFalse(
                    effect.success, f"args {args} should have been rejected"
                )
        finally:
            adapter.close()

    def test_wait_rejects_element_target(self):
        import dataclasses

        permission = _permission()
        adapter, _playwright, identity = _build(permission=permission)
        try:
            observation = adapter.observe(identity.session_id)
            target = BrowserTarget(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserTargetKind.ELEMENT,
                target_id="target-1",
                observed_at=observation.captured_at,
                frame_id="main",
                role="button",
                name="Go",
            )
            session = adapter._sessions[identity.session_id]
            session.last_observation[observation.page_id] = dataclasses.replace(
                observation, target=target
            )
            action = BrowserAction.create(
                session_id=identity.session_id,
                page_id=observation.page_id,
                kind=BrowserActionKind.WAIT,
                target=target,
                args={"text": "x"},
            )
            authority = BrowserActionAuthority.from_observation(
                action, session.last_observation[observation.page_id], permission
            )
            effect = adapter.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("does not accept", effect.error or "")
        finally:
            adapter.close()


class DispatchCompletenessAuditTests(unittest.TestCase):
    """Q5 audit: every declared BrowserActionKind dispatches on the product path.

    Each kind is walked through SemanticPlaywrightManagedBrowser.act with a
    permissive (but real) authority. The assertion is deliberately narrow:
    no kind may fall through to the "not implemented yet" fallback. Shape or
    permission rejections are fine -- they prove a handler claimed the kind.
    """

    def _one(self, adapter, identity, permission, kind, **kwargs):
        return _act(adapter, identity, permission, kind=kind, **kwargs)

    def test_all_declared_kinds_dispatch_without_not_implemented(self):
        permission = _permission()
        adapter, playwright, identity = _build(
            SemanticPlaywrightManagedBrowser, permission=permission
        )
        context = playwright.browser.context
        try:
            page = context.page
            page.url = "https://example.com/home"
            page.inner_text = "welcome home confirmed"

            outcomes = {}

            def run(kind, **kwargs):
                effect = self._one(adapter, identity, permission, kind, **kwargs)
                outcomes[kind.value] = (
                    effect.success,
                    (effect.error or "")[:120],
                )
                self.assertNotIn(
                    "not implemented",
                    (effect.error or "").lower(),
                    f"{kind.value} fell through dispatch: {effect.error}",
                )
                return effect

            # Navigation / tabs / history (tab mixin).
            run(
                BrowserActionKind.OPEN_TAB,
                args={"url": "https://example.com/second"},
                expected={"url_equals": "https://example.com/second"},
            )
            registered = adapter.observe(identity.session_id)
            second_id = registered.metadata["page_ids"][1]
            run(BrowserActionKind.SWITCH_TAB, page_id=second_id)
            run(BrowserActionKind.CLOSE_TAB, page_id=second_id)
            run(
                BrowserActionKind.BACK,
                expected={"url_equals": "https://example.com/previous"},
            )
            run(
                BrowserActionKind.FORWARD,
                expected={"url_equals": "https://example.com/next"},
            )
            run(
                BrowserActionKind.RELOAD,
                expected={"url_equals": "https://example.com/home"},
            )
            run(BrowserActionKind.NAVIGATE, args={"url": "https://example.com/home"})

            # Element handlers that require a target: shape rejections prove dispatch.
            run(BrowserActionKind.CLICK)
            run(BrowserActionKind.FOCUS)
            run(BrowserActionKind.TYPE_TEXT)
            run(BrowserActionKind.SELECT_OPTION)
            run(BrowserActionKind.CHECK)
            run(BrowserActionKind.UNCHECK)
            run(BrowserActionKind.SET_SLIDER_VALUE)

            # File transfer: the mixin claims these kinds, but the authority
            # contract gates them behind explicit upload/download permission,
            # which a plain session does not carry. Both facts together are
            # the explicit conclusion for these two kinds.
            from zn_agent.core.browser_scene_file_transfer import _FILE_ACTIONS

            for kind in (BrowserActionKind.UPLOAD_FILE, BrowserActionKind.DOWNLOAD_FILE):
                self.assertIn(
                    kind,
                    _FILE_ACTIONS,
                    f"{kind.value} is not claimed by the file-transfer mixin",
                )
                action = BrowserAction.create(
                    session_id=identity.session_id,
                    kind=kind,
                )
                observation = adapter.observe(identity.session_id)
                with self.assertRaisesRegex(ValueError, "not permitted"):
                    BrowserActionAuthority.from_observation(
                        action, observation, permission
                    )
                outcomes[kind.value] = (False, "permission-gated, mixin claims kind")

            # Dialogs: explicit failure evidence, not the fallback.
            run(BrowserActionKind.DIALOG_ACCEPT)
            run(BrowserActionKind.DIALOG_DISMISS)

            # Q5 additions.
            run(BrowserActionKind.PRESS, args={"key": "Enter"})
            run(BrowserActionKind.WAIT, args={"text": "confirmed"})

            declared = {kind.value for kind in BrowserActionKind}
            self.assertEqual(set(outcomes), declared)
        finally:
            adapter.close()

    def test_declared_kind_count_matches_audit_baseline(self):
        # The audit ran against 20 kinds. If the enum grows, this test forces
        # the completeness audit above to be re-verified for the new kind.
        self.assertEqual(len(list(BrowserActionKind)), 20)


if __name__ == "__main__":
    unittest.main()
