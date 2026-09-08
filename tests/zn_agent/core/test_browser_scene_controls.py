from __future__ import annotations

import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from zn_agent.core.models import utc_now
from tests.zn_agent.core.test_browser_scene_actions import (
    ORIGIN,
    _Frame,
    _Handle,
    _ItemLocator,
    _Node,
    _Page,
    _authorized,
    _build,
    _permission,
    _target,
)
from tests.zn_agent.core.test_browser_scene_command import _CommandFixture


class _ControlNode(_Node):
    def __init__(
        self,
        *,
        tag="button",
        pressed=None,
        expanded=None,
        selected=None,
        aria_disabled=None,
        href="",
        sensitive=False,
    ):
        super().__init__(tag=tag, sensitive=sensitive)
        self.aria_pressed = pressed
        self.aria_expanded = expanded
        self.aria_selected = selected
        self.aria_disabled = aria_disabled
        self.href = href
        self.click_error = ""


class _ControlHandle(_Handle):
    def evaluate(self, expression, arg=None):
        if (
            "aria-pressed" in expression
            and "aria-expanded" in expression
            and "aria-selected" in expression
        ):
            node = self.node
            return {
                "connected": node.connected,
                "native_disabled": node.disabled,
                "aria_disabled": node.aria_disabled,
                "aria_pressed": node.aria_pressed,
                "aria_expanded": node.aria_expanded,
                "aria_selected": node.aria_selected,
            }
        raw = super().evaluate(expression, arg)
        if isinstance(raw, dict) and "value_length" in raw:
            raw = dict(raw)
            raw["href"] = self.node.href
            if self.node.aria_selected == "true":
                raw["selected"] = True
            elif self.node.aria_selected == "false":
                raw["selected"] = False
        return raw

    def click(self):
        self.node.click_calls += 1
        if self.node.on_mutation is not None:
            self.node.on_mutation()
        if self.node.click_error:
            raise RuntimeError(self.node.click_error)


class _ControlItemLocator(_ItemLocator):
    def element_handle(self):
        return _ControlHandle(self.node)


class _ControlFixture:
    def __init__(
        self,
        *,
        role="button",
        pressed=None,
        expanded=None,
        selected=None,
        aria_disabled=None,
        sensitive=False,
        permission=None,
    ):
        tag = "button" if role in {"button", "tab"} else "div"
        self.node = _ControlNode(
            tag=tag,
            pressed=pressed,
            expanded=expanded,
            selected=selected,
            aria_disabled=aria_disabled,
            sensitive=sensitive,
        )
        self.item = _ControlItemLocator(
            role=role,
            name="State control",
            node=self.node,
        )
        self.main = _Frame(
            url=ORIGIN + "/controls",
            roles={role: [self.item]},
        )
        self.page = _Page(url=self.main.url, main_frame=self.main)
        self.browser, self.identity, self.context, self.provider = _build(
            self.page,
            permission=permission or _permission(navigation=True, text=True),
        )

    def close(self):
        self.browser.close()

    def action(self, expected, *, args=None):
        scene, target = _target(
            self.browser,
            self.identity,
            role=self.item.role,
            name="State control",
        )
        observed, action, authority = _authorized(
            self.browser,
            self.identity,
            target,
            BrowserActionKind.CLICK,
            args=args,
            expected=expected,
        )
        return scene, observed, action, authority


class BrowserSceneControlTests(unittest.TestCase):
    def test_supported_state_transitions_succeed_once(self):
        cases = (
            ("button", "aria_pressed", {"pressed_equals": True}),
            ("button", "aria_expanded", {"expanded_equals": True}),
            ("menuitem", "aria_expanded", {"expanded_equals": True}),
            ("tab", "aria_selected", {"selected_equals": True}),
        )
        for role, attr, expected in cases:
            with self.subTest(role=role, expected=expected):
                kwargs = {
                    "pressed": "false" if attr == "aria_pressed" else None,
                    "expanded": "false" if attr == "aria_expanded" else None,
                    "selected": "false" if attr == "aria_selected" else None,
                }
                fixture = _ControlFixture(role=role, **kwargs)
                fixture.node.on_mutation = lambda n=fixture.node, a=attr: setattr(
                    n, a, "true"
                )
                try:
                    before, _o, action, authority = fixture.action(expected)
                    effect = fixture.browser.act(action, authority)
                    self.assertTrue(effect.success, effect.error)
                    self.assertEqual(fixture.node.click_calls, 1)
                    self.assertEqual(effect.data["dispatch_count"], 1)
                    self.assertIs(effect.data["state_before"], False)
                    self.assertIs(effect.data["state_after"], True)
                    self.assertTrue(effect.data["target_revalidated_before_dispatch"])
                    self.assertTrue(effect.data["page_topology_unchanged"])
                    state = fixture.browser._scene_state(
                        fixture.browser._sessions[fixture.identity.session_id]
                    )
                    self.assertNotIn(before.page_id, state.page_scenes)
                    fresh = fixture.browser.observe_scene(fixture.identity.session_id)
                    self.assertNotEqual(fresh.scene_id, before.scene_id)
                finally:
                    fixture.close()

    def test_expected_false_is_supported(self):
        fixture = _ControlFixture(role="button", pressed="true")
        fixture.node.on_mutation = lambda: setattr(
            fixture.node, "aria_pressed", "false"
        )
        try:
            _scene, _o, action, authority = fixture.action({"pressed_equals": False})
            effect = fixture.browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertIs(effect.data["state_after"], False)
            self.assertEqual(fixture.node.click_calls, 1)
        finally:
            fixture.close()

    def test_already_satisfied_missing_or_malformed_state_refuses_without_click(self):
        cases = (
            (_ControlFixture(role="button", pressed="true"), {"pressed_equals": True}),
            (_ControlFixture(role="button"), {"pressed_equals": True}),
            (_ControlFixture(role="button", pressed="mixed"), {"pressed_equals": True}),
        )
        for fixture, expected in cases:
            try:
                _scene, _o, action, authority = fixture.action(expected)
                effect = fixture.browser.act(action, authority)
                self.assertFalse(effect.success)
                self.assertEqual(fixture.node.click_calls, 0)
            finally:
                fixture.close()

    def test_native_aria_disabled_and_malformed_disabled_refuse_without_click(self):
        native = _ControlFixture(role="button", pressed="false")
        native.node.disabled = True
        aria = _ControlFixture(
            role="button", pressed="false", aria_disabled="true"
        )
        malformed = _ControlFixture(
            role="button", pressed="false", aria_disabled="TRUE"
        )
        for fixture in (native, aria, malformed):
            try:
                _scene, _o, action, authority = fixture.action({"pressed_equals": True})
                effect = fixture.browser.act(action, authority)
                self.assertFalse(effect.success)
                self.assertEqual(fixture.node.click_calls, 0)
            finally:
                fixture.close()

    def test_no_page_interaction_authority_refuses_without_click(self):
        permission = BrowserPermissionContext(
            allow_page_interaction=False,
            allowed_origins=(ORIGIN,),
        )
        fixture = _ControlFixture(role="button", pressed="false", permission=permission)
        try:
            _scene, target = _target(fixture.browser, fixture.identity, role="button")
            observed = fixture.browser.observe_scene_target(
                fixture.identity.session_id,
                target.target_id,
            )
            action = BrowserAction.create(
                session_id=fixture.identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.CLICK,
                target=observed.target,
                expected={"pressed_equals": True},
            )
            authority = BrowserActionAuthority(
                action_id=action.action_id,
                session_id=action.session_id,
                issued_at=utc_now(),
                observation_captured_at=observed.captured_at,
                permission=permission,
                target_id=observed.target.target_id,
                page_id=observed.page_id,
            )
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(fixture.node.click_calls, 0)
        finally:
            fixture.close()

    def test_unsupported_role_state_combinations_refuse_without_click(self):
        cases = (
            ("button", "false", None, None, {"selected_equals": True}),
            ("tab", None, None, "false", {"pressed_equals": True}),
            ("menuitem", None, "false", None, {"pressed_equals": True}),
        )
        for role, pressed, expanded, selected, expected in cases:
            fixture = _ControlFixture(
                role=role,
                pressed=pressed,
                expanded=expanded,
                selected=selected,
            )
            try:
                _scene, _o, action, authority = fixture.action(expected)
                effect = fixture.browser.act(action, authority)
                self.assertFalse(effect.success)
                self.assertEqual(fixture.node.click_calls, 0)
            finally:
                fixture.close()

    def test_multiple_or_nonboolean_postconditions_refuse_without_click(self):
        cases = (
            {"pressed_equals": True, "expanded_equals": True},
            {"pressed_equals": 1},
            {"pressed_equals": "true"},
            {"pressed_equals": None},
        )
        for expected in cases:
            fixture = _ControlFixture(role="button", pressed="false", expanded="false")
            try:
                _scene, _o, action, authority = fixture.action(expected)
                effect = fixture.browser.act(action, authority)
                self.assertFalse(effect.success)
                self.assertEqual(fixture.node.click_calls, 0)
            finally:
                fixture.close()

    def test_all_provider_click_args_refuse_without_click(self):
        args_cases = (
            {"position": {"x": 1, "y": 1}},
            {"modifiers": ["Shift"]},
            {"button": "right"},
            {"click_count": 2},
            {"force": True},
            {"provider_arg": True},
        )
        for args in args_cases:
            fixture = _ControlFixture(role="button", pressed="false")
            try:
                _scene, _o, action, authority = fixture.action(
                    {"pressed_equals": True}, args=args
                )
                effect = fixture.browser.act(action, authority)
                self.assertFalse(effect.success)
                self.assertEqual(fixture.node.click_calls, 0)
            finally:
                fixture.close()

    def test_link_backed_target_refuses_without_click(self):
        fixture = _ControlFixture(role="button", pressed="false")
        fixture.node.tag = "a"
        fixture.node.href = ORIGIN + "/other"
        try:
            _scene, _o, action, authority = fixture.action({"pressed_equals": True})
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(fixture.node.click_calls, 0)
        finally:
            fixture.close()

    def test_replacement_after_authority_is_stale_and_never_dispatches(self):
        fixture = _ControlFixture(role="button", pressed="false")
        try:
            _scene, _o, action, authority = fixture.action({"pressed_equals": True})
            original = fixture.node
            replacement = _ControlNode(tag="button", pressed="false")
            fixture.item.node = replacement
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", (effect.error or "").lower())
            self.assertEqual(original.click_calls, 0)
            self.assertEqual(replacement.click_calls, 0)
        finally:
            fixture.close()

    def test_last_moment_revalidation_catches_replacement_after_prestate(self):
        fixture = _ControlFixture(role="button", pressed="false")
        try:
            _scene, _o, action, authority = fixture.action({"pressed_equals": True})
            original_state = fixture.browser._scene_control_state
            calls = 0
            replacement = _ControlNode(tag="button", pressed="false")

            def state_then_replace(handle, state_name):
                nonlocal calls
                value = original_state(handle, state_name)
                calls += 1
                if calls == 1:
                    fixture.item.node = replacement
                return value

            fixture.browser._scene_control_state = state_then_replace
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", (effect.error or "").lower())
            self.assertEqual(fixture.node.click_calls, 0)
            self.assertEqual(replacement.click_calls, 0)
        finally:
            fixture.close()

    def test_noop_handler_fails_after_one_dispatch_and_invalidates_scene(self):
        fixture = _ControlFixture(role="button", pressed="false")
        try:
            before, _o, action, authority = fixture.action({"pressed_equals": True})
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(fixture.node.click_calls, 1)
            self.assertEqual(effect.data["dispatch_count"], 1)
            self.assertIs(effect.data["state_after"], False)
            state = fixture.browser._scene_state(
                fixture.browser._sessions[fixture.identity.session_id]
            )
            self.assertNotIn(before.page_id, state.page_scenes)
        finally:
            fixture.close()

    def test_post_click_replacement_cannot_be_used_to_prove_success(self):
        fixture = _ControlFixture(role="button", pressed="false")
        replacement = _ControlNode(tag="button", pressed="true")

        def replace_target():
            fixture.node.connected = False
            fixture.item.node = replacement

        fixture.node.on_mutation = replace_target
        try:
            _scene, _o, action, authority = fixture.action({"pressed_equals": True})
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(fixture.node.click_calls, 1)
            self.assertEqual(replacement.click_calls, 0)
            self.assertIsNone(effect.data["state_after"])
        finally:
            fixture.close()

    def test_provider_click_exception_never_retries_invalidates_and_is_privacy_safe(self):
        private_label = "private customer Alice secret label"
        fixture = _ControlFixture(role="button", pressed="false")
        fixture.node.click_error = private_label
        try:
            before, _o, action, authority = fixture.action({"pressed_equals": True})
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(fixture.node.click_calls, 1)
            self.assertEqual(effect.data["dispatch_count"], 1)
            self.assertNotIn(private_label, effect.error or "")
            self.assertNotIn(private_label, repr(effect.data))
            self.assertNotIn("State control", repr(effect.data))
            state = fixture.browser._scene_state(
                fixture.browser._sessions[fixture.identity.session_id]
            )
            self.assertNotIn(before.page_id, state.page_scenes)
        finally:
            fixture.close()

    def test_url_drift_fails_after_one_dispatch(self):
        fixture = _ControlFixture(role="button", pressed="false")

        def mutate():
            fixture.node.aria_pressed = "true"
            fixture.page.url = ORIGIN + "/changed"

        fixture.node.on_mutation = mutate
        try:
            _scene, _o, action, authority = fixture.action({"pressed_equals": True})
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(fixture.node.click_calls, 1)
            self.assertIn("top-level URL", effect.error or "")
        finally:
            fixture.close()

    def test_fresh_page_fails_unclaimed_unclosed_and_unswitched(self):
        fixture = _ControlFixture(role="button", pressed="false")
        extra_main = _Frame(url=ORIGIN + "/popup")
        extra = _Page(url=extra_main.url, main_frame=extra_main, visible=False)

        def mutate():
            fixture.node.aria_pressed = "true"
            extra.context = fixture.context
            fixture.context.pages.append(extra)

        fixture.node.on_mutation = mutate
        try:
            state = fixture.browser._scene_state(
                fixture.browser._sessions[fixture.identity.session_id]
            )
            default_before = fixture.browser._sessions[
                fixture.identity.session_id
            ].default_page_id
            _scene, _o, action, authority = fixture.action({"pressed_equals": True})
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(fixture.node.click_calls, 1)
            self.assertEqual(effect.data["new_page_count"], 1)
            self.assertEqual(effect.data["new_page_ids"], [])
            self.assertTrue(effect.data["fresh_pages_unclaimed"])
            session = fixture.browser._sessions[fixture.identity.session_id]
            self.assertEqual(session.default_page_id, default_before)
            self.assertEqual(len(session.pages), 1)
            self.assertNotIn("page-2", state.page_ownership)
            self.assertEqual(extra.close_calls, 0)
            self.assertIn(extra, fixture.context.pages)
        finally:
            fixture.close()

    def test_stateless_command_routing_still_wins(self):
        fixture = _CommandFixture()
        fixture.trigger.on_mutation = fixture.remove_rows
        try:
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            self.assertTrue(fixture.browser._scene_command_is_action(action))
            self.assertFalse(fixture.browser._scene_control_is_action(action))
            effect = fixture.browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(fixture.trigger.click_calls, 1)
        finally:
            fixture.close()

    def test_navigation_url_equals_still_routes_to_existing_scene_action(self):
        fixture = _ControlFixture(role="button")
        destination = ORIGIN + "/done"
        fixture.node.on_mutation = lambda: setattr(fixture.page, "url", destination)
        try:
            _scene, _o, action, authority = fixture.action({"url_equals": destination})
            self.assertFalse(fixture.browser._scene_control_is_action(action))
            self.assertFalse(fixture.browser._scene_command_is_action(action))
            effect = fixture.browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(fixture.node.click_calls, 1)
            self.assertEqual(effect.url_after, destination)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
