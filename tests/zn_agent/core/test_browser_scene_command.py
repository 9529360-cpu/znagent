from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from tests.zn_agent.core.test_browser_scene_actions import (
    ORIGIN,
    _Frame,
    _ItemLocator,
    _Node,
    _Page,
    _authorized,
    _build,
    _permission,
    _target,
)


_COMPLETION_ROLE = "row"
_COMPLETION_NAME = "Invoice 42"


class _CommandPage(_Page):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.history_marker = {
            "length": 1,
            "entry_key": "entry-1",
            "entry_id": "entry-1",
        }

    def evaluate(self, expression):
        if "globalThis.history" in expression:
            return dict(self.history_marker)
        return super().evaluate(expression)


class _CommandFixture:
    def __init__(
        self,
        *,
        trigger_role="button",
        completion_count=1,
        user=False,
        permission=None,
    ):
        self.trigger = _Node(tag="button" if trigger_role == "button" else "div")
        self.trigger_item = _ItemLocator(
            role=trigger_role,
            name="Delete",
            node=self.trigger,
        )
        self.rows = [
            _ItemLocator(
                role=_COMPLETION_ROLE,
                name=_COMPLETION_NAME,
                node=_Node(tag="tr"),
            )
            for _ in range(completion_count)
        ]
        self.main = _Frame(
            url=ORIGIN + "/commands",
            roles={
                trigger_role: [self.trigger_item],
                _COMPLETION_ROLE: self.rows,
            },
        )
        self.page = _CommandPage(url=self.main.url, main_frame=self.main)
        self.browser, self.identity, self.context, self.provider = _build(
            self.page,
            permission=permission or _permission(navigation=True, text=True),
            user=user,
        )

    def close(self):
        if self.identity.plane.value == "user":
            self.browser.close_session(self.identity.session_id)
        else:
            self.browser.close()

    def action(self, *, expected=None, args=None):
        _scene, target = _target(
            self.browser,
            self.identity,
            role=self.trigger_item.role,
            name="Delete",
        )
        return _authorized(
            self.browser,
            self.identity,
            target,
            BrowserActionKind.CLICK,
            args=args,
            expected=expected,
        )

    @staticmethod
    def descriptor(*, role=_COMPLETION_ROLE, name=_COMPLETION_NAME):
        return {
            "target_absent_equals": {
                "role": role,
                "accessible_name": name,
            }
        }

    def remove_rows(self):
        self.main.roles[_COMPLETION_ROLE] = []
        for row in self.rows:
            row.node.connected = False


class BrowserSceneCommandTests(unittest.TestCase):
    def test_routing_is_narrow_and_does_not_steal_existing_actions(self):
        fixture = _CommandFixture()
        try:
            observed, command, _authority = fixture.action(expected=fixture.descriptor())
            self.assertTrue(fixture.browser._scene_command_is_action(command))

            for kind, expected in (
                (BrowserActionKind.CLICK, {"url_equals": ORIGIN + "/done"}),
                (BrowserActionKind.CLICK, {"popup_url_equals": ORIGIN + "/popup"}),
                (BrowserActionKind.UPLOAD_FILE, {}),
                (BrowserActionKind.DOWNLOAD_FILE, {}),
                (BrowserActionKind.FOCUS, {}),
                (BrowserActionKind.TYPE_TEXT, {}),
                (BrowserActionKind.CHECK, {}),
                (BrowserActionKind.SWITCH_TAB, {}),
            ):
                action = BrowserAction.create(
                    session_id=fixture.identity.session_id,
                    page_id=observed.page_id,
                    kind=kind,
                    target=observed.target,
                    expected=expected,
                )
                self.assertFalse(
                    fixture.browser._scene_command_is_action(action),
                    (kind, expected),
                )
        finally:
            fixture.close()

    def test_schema_is_exact_and_privacy_bounded(self):
        cases = (
            ({"force": True}, _CommandFixture.descriptor()),
            ({}, {**_CommandFixture.descriptor(), "extra": True}),
            ({}, {"target_absent_equals": {"role": "row"}}),
            ({}, {"target_absent_equals": {"role": "row", "accessible_name": _COMPLETION_NAME, "extra": True}}),
            ({}, {"target_absent_equals": {"role": "", "accessible_name": _COMPLETION_NAME}}),
            ({}, {"target_absent_equals": {"role": "row", "accessible_name": ""}}),
            ({}, {"target_absent_equals": {"role": "row", "accessible_name": "x" * 257}}),
            ({}, {"target_absent_equals": {"role": "row", "accessible_name": "bad\nname"}}),
            ({}, {"target_absent_equals": {"role": " row", "accessible_name": _COMPLETION_NAME}}),
        )
        for args, expected in cases:
            with self.subTest(args=args, expected=expected):
                fixture = _CommandFixture()
                try:
                    _o, action, authority = fixture.action(args=args, expected=expected)
                    effect = fixture.browser.act(action, authority)
                    self.assertFalse(effect.success)
                    self.assertEqual(fixture.trigger.click_calls, 0)
                    self.assertNotIn(_COMPLETION_NAME, effect.error or "")
                finally:
                    fixture.close()

    def test_button_and_menuitem_are_the_only_first_slice_trigger_roles(self):
        for role, should_succeed in (
            ("button", True),
            ("menuitem", True),
            ("link", False),
            ("checkbox", False),
            ("radio", False),
            ("tab", False),
            ("row", False),
        ):
            with self.subTest(role=role):
                fixture = _CommandFixture(trigger_role=role)
                fixture.trigger.on_mutation = fixture.remove_rows
                try:
                    _o, action, authority = fixture.action(expected=fixture.descriptor())
                    effect = fixture.browser.act(action, authority)
                    self.assertEqual(effect.success, should_succeed, effect.error)
                    self.assertEqual(fixture.trigger.click_calls, 1 if should_succeed else 0)
                finally:
                    fixture.close()

    def test_unique_before_absent_after_is_verified_once_with_private_evidence(self):
        fixture = _CommandFixture()
        fixture.trigger.on_mutation = fixture.remove_rows
        try:
            before = fixture.browser.observe_scene(fixture.identity.session_id)
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            effect = fixture.browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(fixture.trigger.click_calls, 1)
            self.assertEqual(effect.data["dispatch_count"], 1)
            self.assertEqual(effect.data["matching_target_count_before"], 1)
            self.assertEqual(effect.data["matching_target_count_after"], 0)
            self.assertTrue(effect.data["target_revalidated_before_dispatch"])
            self.assertTrue(effect.data["page_topology_unchanged"])
            self.assertEqual(effect.url_before, fixture.page.url)
            self.assertEqual(effect.url_after, fixture.page.url)
            self.assertEqual(effect.data["name_length"], len(_COMPLETION_NAME))
            self.assertEqual(
                effect.data["name_sha256"],
                hashlib.sha256(_COMPLETION_NAME.encode("utf-8")).hexdigest(),
            )
            self.assertNotIn(_COMPLETION_NAME, repr(effect.data))
            fresh = fixture.browser.observe_scene(fixture.identity.session_id)
            self.assertNotEqual(fresh.scene_id, before.scene_id)
            self.assertFalse(
                any(
                    target.role == _COMPLETION_ROLE
                    and target.accessible_name == _COMPLETION_NAME
                    for target in fresh.targets
                )
            )
        finally:
            fixture.close()

    def test_zero_or_multiple_precondition_matches_refuse_without_click(self):
        for count, fragment in ((0, "already absent"), (2, "ambiguous")):
            with self.subTest(count=count):
                fixture = _CommandFixture(completion_count=count)
                try:
                    _o, action, authority = fixture.action(expected=fixture.descriptor())
                    effect = fixture.browser.act(action, authority)
                    self.assertFalse(effect.success)
                    self.assertIn(fragment, effect.error or "")
                    self.assertEqual(fixture.trigger.click_calls, 0)
                finally:
                    fixture.close()

    def test_current_truncated_scene_refuses_without_click(self):
        fixture = _CommandFixture()
        try:
            _scene, target = _target(fixture.browser, fixture.identity, role="button", name="Delete")
            state = fixture.browser._scene_state(fixture.browser._sessions[fixture.identity.session_id])
            page_state = state.page_scenes[_scene.page_id]
            page_state.scene = replace(page_state.scene, truncated=True)
            observed = fixture.browser.observe_scene_target(
                fixture.identity.session_id,
                target.target_id,
                page_id=_scene.page_id,
            )
            action = BrowserAction.create(
                session_id=fixture.identity.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.CLICK,
                target=observed.target,
                expected=fixture.descriptor(),
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observed,
                fixture.browser._sessions[fixture.identity.session_id].permission,
            )
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("non-truncated current scene", effect.error or "")
            self.assertEqual(fixture.trigger.click_calls, 0)
        finally:
            fixture.close()

    def test_stale_and_last_moment_replacement_both_refuse_without_click(self):
        fixture = _CommandFixture()
        try:
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            original = fixture.trigger
            fixture.trigger_item.node = _Node(tag="button")
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", (effect.error or "").lower())
            self.assertEqual(original.click_calls, 0)
        finally:
            fixture.close()

        fixture = _CommandFixture()
        try:
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            original_check = fixture.browser._scene_command_require_stateless_trigger
            replacement = _Node(tag="button")

            def replace_after_precheck(binding):
                original_check(binding)
                fixture.trigger_item.node = replacement

            fixture.browser._scene_command_require_stateless_trigger = replace_after_precheck
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("stale", (effect.error or "").lower())
            self.assertEqual(fixture.trigger.click_calls, 0)
            self.assertEqual(replacement.click_calls, 0)
        finally:
            fixture.close()

    def test_target_remains_or_duplicates_after_click_fail_without_retry(self):
        fixture = _CommandFixture()
        try:
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("remained present", effect.error or "")
            self.assertEqual(effect.data["matching_target_count_after"], 1)
            self.assertEqual(fixture.trigger.click_calls, 1)
            self.assertEqual(effect.data["dispatch_count"], 1)
        finally:
            fixture.close()

        fixture = _CommandFixture()
        def duplicate():
            fixture.main.roles[_COMPLETION_ROLE].append(
                _ItemLocator(
                    role=_COMPLETION_ROLE,
                    name=_COMPLETION_NAME,
                    node=_Node(tag="tr"),
                )
            )
        fixture.trigger.on_mutation = duplicate
        try:
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(effect.data["matching_target_count_after"], 2)
            self.assertEqual(fixture.trigger.click_calls, 1)
        finally:
            fixture.close()

    def test_fresh_scene_truncation_or_observation_failure_never_retries(self):
        fixture = _CommandFixture()
        fixture.trigger.on_mutation = fixture.remove_rows
        original_observe = fixture.browser.observe_scene
        def truncated(*args, **kwargs):
            return replace(original_observe(*args, **kwargs), truncated=True)
        fixture.browser.observe_scene = truncated
        try:
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("truncated fresh scene", effect.error or "")
            self.assertEqual(fixture.trigger.click_calls, 1)
        finally:
            fixture.close()

        fixture = _CommandFixture()
        fixture.trigger.on_mutation = fixture.remove_rows
        original_observe = fixture.browser.observe_scene
        calls = 0
        def fail_after_dispatch(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls >= 1:
                raise RuntimeError("provider detail containing private label")
            return original_observe(*args, **kwargs)
        try:
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            fixture.browser.observe_scene = fail_after_dispatch
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("fresh scene acquisition failed", effect.error or "")
            self.assertNotIn("private label", effect.error or "")
            self.assertEqual(fixture.trigger.click_calls, 1)
        finally:
            fixture.close()

    def test_url_history_and_topology_changes_fail_closed(self):
        fixture = _CommandFixture()
        fixture.trigger.on_mutation = lambda: setattr(fixture.page, "url", ORIGIN + "/changed")
        try:
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("top-level URL", effect.error or "")
            self.assertEqual(fixture.trigger.click_calls, 1)
        finally:
            fixture.close()

        fixture = _CommandFixture()
        def history_change():
            fixture.page.history_marker = {
                "length": 2,
                "entry_key": "entry-2",
                "entry_id": "entry-2",
            }
        fixture.trigger.on_mutation = history_change
        try:
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("history state", effect.error or "")
            self.assertEqual(fixture.trigger.click_calls, 1)
        finally:
            fixture.close()

        fixture = _CommandFixture()
        extra = _CommandPage(url=ORIGIN + "/popup", main_frame=_Frame(url=ORIGIN + "/popup"), visible=False)
        def popup():
            extra.context = fixture.context
            fixture.context.pages.append(extra)
        fixture.trigger.on_mutation = popup
        try:
            state = fixture.browser._scene_state(fixture.browser._sessions[fixture.identity.session_id])
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("top-level page topology", effect.error or "")
            self.assertEqual(effect.data["new_page_count"], 1)
            self.assertEqual(effect.data["new_page_ids"], [])
            self.assertTrue(effect.data["fresh_pages_unclaimed"])
            self.assertIn(extra, fixture.context.pages)
            self.assertNotIn("page-2", state.page_ownership)
            self.assertEqual(getattr(extra, "close_calls", 0), 0)
        finally:
            fixture.close()

    def test_out_of_scope_post_click_url_fails_closed(self):
        fixture = _CommandFixture(
            permission=BrowserPermissionContext(
                allow_page_interaction=True,
                allowed_origins=(ORIGIN,),
            )
        )
        fixture.trigger.on_mutation = lambda: setattr(fixture.page, "url", "https://other.test/private")
        try:
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertEqual(fixture.trigger.click_calls, 1)
            self.assertEqual(effect.url_after, "")
        finally:
            fixture.close()

    def test_dispatched_failure_invalidates_old_scene_authority(self):
        fixture = _CommandFixture()
        try:
            scene = fixture.browser.observe_scene(fixture.identity.session_id)
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            effect = fixture.browser.act(action, authority)
            self.assertFalse(effect.success)
            state = fixture.browser._scene_state(fixture.browser._sessions[fixture.identity.session_id])
            self.assertNotIn(scene.page_id, state.page_scenes)
            self.assertEqual(fixture.trigger.click_calls, 1)
        finally:
            fixture.close()

    def test_user_plane_keeps_existing_same_page_command_authority(self):
        fixture = _CommandFixture(user=True)
        fixture.trigger.on_mutation = fixture.remove_rows
        try:
            _o, action, authority = fixture.action(expected=fixture.descriptor())
            before_pages = list(fixture.context.pages)
            effect = fixture.browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(fixture.context.pages, before_pages)
            self.assertEqual(fixture.provider.close_calls, 0)
            self.assertEqual(fixture.trigger.click_calls, 1)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
