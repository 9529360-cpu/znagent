from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserActionAuthority,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
    BrowserTarget,
    BrowserTargetKind,
)
from zn_agent.core.browser_loop import execute_browser_loop_step
from zn_agent.core.browser_multipage_context import (
    BrowserMultiPageContext,
    BrowserPageRecord,
    load_multipage_context,
    store_multipage_context,
)
from zn_agent.core.models import utc_now


FORM_URL = "https://example.test/form"
OTHER_URL = "https://example.test/other"
DRIFTED_URL = "https://example.test/changed"


def _permission() -> BrowserPermissionContext:
    return BrowserPermissionContext(
        allow_navigation=True,
        allow_page_interaction=True,
        allow_text_entry=True,
    )


class _MultiPageBrowser:
    """Mock provider with independent per-page state and page_id targeting."""

    name = "multipage-fixture"
    plane = BrowserPlane.MANAGED

    def __init__(self) -> None:
        self.identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.MANAGED,
            provider=self.name,
            browser_name="chromium",
        )
        self.pages = {
            "page-1": {"url": FORM_URL, "title": "Form A", "load_state": "complete"},
            "page-2": {"url": OTHER_URL, "title": "Form B", "load_state": "complete"},
        }
        self.gone: set[str] = set()
        self.act_calls = 0
        self.observe_calls = 0

    def open_session(self, *, permission=None, headless=True, owner=None):
        return self.identity

    def close_session(self, session_id):
        return None

    def _observe_page(self, page_id: str) -> BrowserObservation:
        if page_id in self.gone or page_id not in self.pages:
            raise RuntimeError(f"page {page_id} is gone")
        state = self.pages[page_id]
        return BrowserObservation(
            session=self.identity,
            page_id=page_id,
            captured_at=utc_now(),
            url=state["url"],
            title=state["title"],
            load_state=state["load_state"],
        )

    def observe(self, session_id, *, page_id=""):
        self.observe_calls += 1
        return self._observe_page(page_id or "page-1")

    def observe_target(self, session_id, query, *, page_id=""):
        target_page = page_id or "page-1"
        state = self.pages[target_page]
        target = BrowserTarget(
            session_id=self.identity.session_id,
            page_id=target_page,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id="target-1",
            observed_at=utc_now(),
            url=state["url"],
            frame_id="main",
            role="button",
            name=query.value,
            selector_hint="accessible_button_name:exact",
        )
        observation = self._observe_page(target_page)
        return BrowserObservation(
            session=self.identity,
            page_id=target_page,
            captured_at=observation.captured_at,
            url=observation.url,
            title=observation.title,
            load_state=observation.load_state,
            target=target,
        )

    def act(self, action, authority: BrowserActionAuthority):
        self.act_calls += 1
        state = self.pages[action.page_id]
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=action.page_id,
            url_before=state["url"],
            url_after=state["url"],
            target_id=action.target.target_id if action.target else "",
            postcondition="fixture action applied",
        )


def _register(context: BrowserMultiPageContext, provider, page_id: str, role: str = "part"):
    return context.register_page(
        page_id,
        task_role=role,
        note=f"note for {page_id}",
        observation=provider.observe("session-1", page_id=page_id),
    )


class BrowserMultiPageContextTest(unittest.TestCase):
    def setUp(self):
        self.provider = _MultiPageBrowser()
        self.context = BrowserMultiPageContext()

    def test_register_and_clean_return_reobserves(self):
        record = _register(self.context, self.provider, "page-1", role="fill the form")
        self.assertEqual(record.url, FORM_URL)
        self.assertEqual(record.task_role, "fill the form")

        outcome = self.context.return_to_page(
            self.provider, session_id="session-1", page_id="page-1"
        )
        self.assertFalse(outcome.drifted)
        self.assertEqual(outcome.drift_reason, "")
        self.assertEqual(outcome.fresh_observation.url, FORM_URL)
        self.assertEqual(outcome.record.reobservations, 1)
        # Nothing was dispatched: returning is read-only.
        self.assertEqual(self.provider.act_calls, 0)
        self.assertEqual(self.provider.observe_calls, 2)

    def test_return_detects_url_drift_and_refreshes_record(self):
        _register(self.context, self.provider, "page-1", role="fill the form")
        # While the Work is away on page B, page A changes.
        self.provider.pages["page-1"]["url"] = DRIFTED_URL

        outcome = self.context.return_to_page(
            self.provider, session_id="session-1", page_id="page-1"
        )
        self.assertTrue(outcome.drifted)
        self.assertIn(FORM_URL, outcome.drift_reason)
        self.assertIn(DRIFTED_URL, outcome.drift_reason)
        # The stored record is refreshed to the fresh state: the stale
        # snapshot can never be reused silently afterwards.
        refreshed = self.context.get_page("page-1")
        self.assertEqual(refreshed.url, DRIFTED_URL)
        self.assertEqual(refreshed.drift_events, 1)
        kinds = [event["kind"] for event in self.context.events()]
        self.assertIn("page_return", kinds)
        drifted_events = [e for e in self.context.events() if e.get("drifted")]
        self.assertEqual(len(drifted_events), 1)

    def test_return_detects_failed_load_state(self):
        _register(self.context, self.provider, "page-1")
        self.provider.pages["page-1"]["load_state"] = "crashed"

        outcome = self.context.return_to_page(
            self.provider, session_id="session-1", page_id="page-1"
        )
        self.assertTrue(outcome.drifted)
        self.assertIn("failed load state", outcome.drift_reason)

    def test_return_to_gone_page_is_explicit_drift(self):
        _register(self.context, self.provider, "page-1")
        self.provider.gone.add("page-1")

        outcome = self.context.return_to_page(
            self.provider, session_id="session-1", page_id="page-1"
        )
        self.assertTrue(outcome.drifted)
        self.assertIn("could not be re-observed", outcome.drift_reason)
        self.assertIsNone(outcome.fresh_observation)
        # The stale record is kept (there is no fresh state) but marked.
        self.assertEqual(self.context.get_page("page-1").drift_events, 1)

    def test_return_to_unregistered_page_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self.context.return_to_page(
                self.provider, session_id="session-1", page_id="page-9"
            )
        self.assertIn("no record", str(ctx.exception))

    def test_register_requires_fresh_observation(self):
        with self.assertRaises(ValueError):
            self.context.register_page("page-1", task_role="part")

    def test_caps_fail_closed(self):
        observation = self.provider.observe("session-1", page_id="page-1")
        with self.assertRaises(ValueError):
            self.context.register_page("page-1", task_role="x" * 257, observation=observation)
        with self.assertRaises(ValueError):
            self.context.register_page(
                "page-1", task_role="part", note="y" * 513, observation=observation
            )
        for index in range(8):
            self.context.register_page(
                f"page-extra-{index}",
                task_role="part",
                observation=observation,
            )
        with self.assertRaises(ValueError):
            self.context.register_page(
                "page-overflow", task_role="part", observation=observation
            )
        with self.assertRaises(ValueError):
            self.context.register_page("  ", task_role="part", observation=observation)

    def test_round_trip_and_junk_rejected(self):
        _register(self.context, self.provider, "page-1", role="fill the form")
        _register(self.context, self.provider, "page-2", role="look up reference")
        data = self.context.to_dict()

        restored = BrowserMultiPageContext.from_dict(data)
        self.assertEqual(restored.get_page("page-1").task_role, "fill the form")
        self.assertEqual(restored.get_page("page-2").url, OTHER_URL)

        with self.assertRaises(ValueError):
            BrowserMultiPageContext.from_dict({"pages": "nope"})
        with self.assertRaises(ValueError):
            BrowserMultiPageContext.from_dict({"pages": [{"page_id": "p"}]})
        with self.assertRaises(ValueError):
            BrowserPageRecord.from_dict({"page_id": "p", "task_role": 5})

    def test_describe_summarizes_task_parts(self):
        _register(self.context, self.provider, "page-1", role="fill the form")
        summary = self.context.describe()
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["page_id"], "page-1")
        self.assertEqual(summary[0]["task_role"], "fill the form")
        self.assertEqual(summary[0]["url"], FORM_URL)

    def test_load_store_round_trip_in_session_dict(self):
        session: dict = {}
        _register(self.context, self.provider, "page-1", role="fill the form")
        store_multipage_context(session, self.context)
        loaded = load_multipage_context(session)
        self.assertEqual(loaded.get_page("page-1").task_role, "fill the form")
        empty = load_multipage_context({})
        self.assertEqual(empty.known_pages(), ())


class BrowserPageLoopActionsTest(unittest.TestCase):
    """A -> B -> back to A through the real browser loop steps (mock provider)."""

    def setUp(self):
        self.provider = _MultiPageBrowser()
        self.permission = _permission()

    def _step(self, session, action_id, arguments):
        return execute_browser_loop_step(
            self.provider,
            session=session,
            permission=self.permission,
            action_id=action_id,
            arguments=arguments,
        )

    def test_a_to_b_back_to_a_uses_fresh_state(self):
        # A: navigate opens the loop session on page-1.
        navigated = self._step(
            None,
            "browser.navigate",
            {"url": FORM_URL, "expected_url": FORM_URL},
        )
        self.assertTrue(navigated.execution.success)
        session = dict(navigated.session)
        self.assertEqual(session["page_id"], "page-1")

        # Register A as the form-filling task part, then go to B.
        registered_a = self._step(
            session,
            "browser.page.register",
            {"task_role": "fill the order form", "note": "step 2 of 4"},
        )
        self.assertTrue(registered_a.execution.success)
        session = dict(registered_a.session)
        self.assertEqual(
            registered_a.execution.verification.evidence["page"]["task_role"],
            "fill the order form",
        )
        registered_b = self._step(
            session,
            "browser.page.register",
            {"task_role": "look up reference price", "page_id": "page-2"},
        )
        self.assertTrue(registered_b.execution.success)
        session = dict(registered_b.session)
        self.assertEqual(session["page_id"], "page-2")
        self.assertEqual(len(session["multipage_context"]["pages"]), 2)

        # Back to A: freshly re-observed, no drift, task part remembered.
        acts_before_return = self.provider.act_calls
        returned = self._step(session, "browser.page.return", {"page_id": "page-1"})
        self.assertTrue(returned.execution.success)
        session = dict(returned.session)
        self.assertEqual(session["page_id"], "page-1")
        self.assertEqual(session["url"], FORM_URL)
        evidence = returned.execution.verification.evidence
        self.assertFalse(evidence["drifted"])
        self.assertEqual(evidence["page"]["task_role"], "fill the order form")
        # Return dispatched nothing.
        self.assertEqual(self.provider.act_calls, acts_before_return)

        # Continuing the original task on A now pins the fresh A state.
        clicked = self._step(
            session,
            "browser.semantic_click",
            {"target_name": "Submit"},
        )
        self.assertTrue(clicked.execution.success)
        self.assertEqual(self.provider.act_calls, acts_before_return + 1)

    def test_drift_on_return_fails_explicitly_and_refreshes_pin(self):
        navigated = self._step(None, "browser.navigate", {"url": FORM_URL})
        session = dict(navigated.session)
        registered = self._step(
            session, "browser.page.register", {"task_role": "fill the order form"}
        )
        session = dict(registered.session)

        # Page A changes while the Work is away.
        self.provider.pages["page-1"]["url"] = DRIFTED_URL

        returned = self._step(session, "browser.page.return", {"page_id": "page-1"})
        self.assertFalse(returned.execution.success)
        reason = returned.execution.error or ""
        self.assertIn("drifted", reason)
        self.assertIn(DRIFTED_URL, reason)
        # The session pin is refreshed to the fresh state: the Work cannot
        # go on acting on the remembered URL.
        session = dict(returned.session)
        self.assertEqual(session["url"], DRIFTED_URL)
        # The retention context was refreshed too.
        context = load_multipage_context(session)
        self.assertEqual(context.get_page("page-1").url, DRIFTED_URL)
        self.assertEqual(context.get_page("page-1").drift_events, 1)

        # The next semantic proposal pins the *fresh* URL, not the stale one.
        clicked = self._step(
            session,
            "browser.semantic_click",
            {"target_name": "Submit"},
        )
        self.assertTrue(clicked.execution.success)

    def test_return_without_registration_fails_closed(self):
        navigated = self._step(None, "browser.navigate", {"url": FORM_URL})
        returned = self._step(
            dict(navigated.session), "browser.page.return", {"page_id": "page-1"}
        )
        self.assertFalse(returned.execution.success)
        self.assertIn("no record", returned.execution.error or "")

    def test_return_without_session_fails_closed(self):
        returned = self._step(
            {}, "browser.page.return", {"page_id": "page-1"}
        )
        self.assertFalse(returned.execution.success)

    def test_context_survives_plain_observe_steps(self):
        navigated = self._step(None, "browser.navigate", {"url": FORM_URL})
        session = dict(navigated.session)
        registered = self._step(
            session, "browser.page.register", {"task_role": "fill the order form"}
        )
        session = dict(registered.session)
        observed = self._step(session, "browser.observe", {})
        session = dict(observed.session)
        self.assertEqual(len(session["multipage_context"]["pages"]), 1)
        returned = self._step(session, "browser.page.return", {"page_id": "page-1"})
        self.assertTrue(returned.execution.success)

    def test_register_rejects_unknown_arguments(self):
        navigated = self._step(None, "browser.navigate", {"url": FORM_URL})
        # Unknown arguments fail closed at proposal validation (existing loop
        # behavior: ValueError from validate_browser_loop_arguments).
        with self.assertRaises(ValueError) as ctx:
            self._step(
                dict(navigated.session),
                "browser.page.register",
                {"task_role": "fill the form", "bogus": "x"},
            )
        self.assertIn("rejects unknown arguments", str(ctx.exception))

    def test_catalog_lists_new_actions(self):
        from zn_agent.core.browser_loop import browser_loop_catalog

        ids = [row["action_id"] for row in browser_loop_catalog()]
        self.assertIn("browser.page.register", ids)
        self.assertIn("browser.page.return", ids)


if __name__ == "__main__":
    unittest.main()
