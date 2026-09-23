from __future__ import annotations

import hashlib
import json
import unittest

from zn_agent.core.browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from zn_agent.core.managed_browser import PlaywrightManagedBrowser


class _ValueHandle:
    def __init__(self, value):
        self.value = value

    def json_value(self):
        return self.value

    def dispose(self):
        return None


class _ElementHandle:
    def __init__(self, page, node):
        self.page = page
        self.node = node
        self.disposed = False

    def as_element(self):
        return self

    def evaluate(self, expression, arg=None):
        if self.disposed:
            raise RuntimeError("disposed element")
        if "element === other" in expression:
            return isinstance(arg, _ElementHandle) and self.node is arg.node
        if "matching_count" in expression and "same_label_count" in expression:
            request = arg if isinstance(arg, dict) else {}
            mode = str(request.get("mode") or "")
            requested = str(request.get("requested") or "")
            raw_options = self.node.get("options")
            if isinstance(raw_options, list):
                options = [
                    {"value": str(item.get("value") or ""), "label": str(item.get("label") or "")}
                    for item in raw_options
                    if isinstance(item, dict)
                ]
            else:
                current_value = str(self.node.get("selected", ""))
                current_label = str(
                    self.node.get("selected_label", self.node.get("selected", ""))
                )
                options = [{"value": current_value, "label": current_label}]
                if mode == "value":
                    requested_value = requested
                    requested_label = str(
                        self.node.get("value_labels", {}).get(requested, requested)
                    )
                    requested_field = requested_value
                    current_field = current_value
                else:
                    requested_label = requested
                    requested_value = str(
                        self.node.get("label_values", {}).get(requested, requested)
                    )
                    requested_field = requested_label
                    current_field = current_label
                if requested_field != current_field:
                    options.append(
                        {"value": requested_value, "label": requested_label}
                    )
            field = "value" if mode == "value" else "label"
            matches = [item for item in options if item[field] == requested]
            if len(matches) != 1:
                return {
                    "connected": bool(self.node.get("connected", True)),
                    "supported": bool(self.node.get("supported", True)),
                    "disabled": bool(self.node.get("disabled", False)),
                    "multiple": bool(self.node.get("multiple", False)),
                    "matching_count": len(matches),
                    "same_label_count": 0,
                    "label": "",
                    "value": "",
                }
            choice = matches[0]
            same_label_count = sum(
                item["label"] == choice["label"] for item in options
            )
            return {
                "connected": bool(self.node.get("connected", True)),
                "supported": bool(self.node.get("supported", True)),
                "disabled": bool(self.node.get("disabled", False)),
                "multiple": bool(self.node.get("multiple", False)),
                "matching_count": 1,
                "same_label_count": same_label_count,
                "label": choice["label"],
                "value": choice["value"],
            }
        if "selectedOptions" in expression and "element.multiple" in expression:
            connected = bool(self.node.get("connected", True))
            supported = bool(self.node.get("supported", True))
            selected_values = (
                [str(self.node.get("selected", ""))] if connected and supported else []
            )
            selected_labels = (
                [str(self.node.get("selected_label", self.node.get("selected", "")))]
                if connected and supported
                else []
            )
            return {
                "connected": connected,
                "supported": supported,
                "disabled": bool(self.node.get("disabled", False)),
                "multiple": bool(self.node.get("multiple", False)),
                "selected_values": selected_values,
                "selected_labels": selected_labels,
            }
        if "document.querySelectorAll" in expression and "element.isConnected" in expression:
            current = self.page.node
            connected = bool(self.node.get("connected", True))
            tag = "select" if self.node.get("supported", True) else "div"
            return {
                "count": 1,
                "current": bool(connected and current is self.node),
                "connected": connected,
                "visible": connected,
                "dom_id": "select-target",
                "tag": tag,
                "role": "combobox" if tag == "select" else "",
                "name": "Select target",
                "input_type": "",
                "is_password": False,
            }
        raise AssertionError("unexpected evaluate expression")

    def select_option(self, *, value=None, label=None):
        if self.disposed or not self.node.get("connected", True):
            raise RuntimeError("detached element")
        if (value is None) == (label is None):
            raise RuntimeError("fake select requires exactly one value or label")
        self.page.select_dispatches += 1
        if self.node.get("select_error"):
            raise RuntimeError("provider select error")
        if not self.node.get("select_blocked"):
            if value is not None:
                self.node["selected"] = value
                self.node["selected_label"] = self.node.get("value_labels", {}).get(
                    value, value
                )
            else:
                self.node["selected_label"] = label
                self.node["selected"] = self.node.get("label_values", {}).get(
                    label, label
                )
        if self.node.get("replace_on_select"):
            replacement = dict(self.node)
            replacement.pop("replace_on_select", None)
            self.node["connected"] = False
            replacement["connected"] = True
            self.page.node = replacement
        return [value]

    def dispose(self):
        self.disposed = True


class _BundleHandle:
    def __init__(self, page):
        self.page = page

    def get_property(self, name):
        if name == "count":
            return _ValueHandle(1)
        if name == "node":
            return _ElementHandle(self.page, self.page.node)
        raise AssertionError(name)

    def dispose(self):
        return None


class _Page:
    def __init__(self, node):
        self.node = node
        self.url = "https://example.com/select"
        self.viewport_size = {"width": 800, "height": 600}
        self.select_dispatches = 0

    def title(self):
        return "Select"

    def evaluate(self, expression):
        if expression == "document.readyState":
            return "complete"
        raise AssertionError(expression)

    def evaluate_handle(self, expression, arg=None):
        if "document.querySelectorAll" not in expression or arg != "select-target":
            raise AssertionError("unexpected target query")
        return _BundleHandle(self)

    def is_closed(self):
        return False


class _Context:
    def __init__(self, page):
        self.page = page

    def set_default_navigation_timeout(self, value):
        return None

    def set_default_timeout(self, value):
        return None

    def route(self, pattern, handler):
        return None

    def route_web_socket(self, pattern, handler):
        return None

    def new_page(self):
        return self.page

    def close(self):
        return None


class _Browser:
    version = "fake"

    def __init__(self, page):
        self.context = _Context(page)

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        return None


class _Chromium:
    def __init__(self, browser):
        self.browser = browser

    def launch(self, *, headless):
        return self.browser


class _Playwright:
    def __init__(self, page):
        self.chromium = _Chromium(_Browser(page))

    def stop(self):
        return None


class _Starter:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def _build(node, *, permission=None):
    page = _Page(node)
    playwright = _Playwright(page)
    policy = permission or BrowserPermissionContext(allow_page_interaction=True)
    browser = PlaywrightManagedBrowser(
        playwright_factory=lambda: _Starter(playwright),
        url_checker=lambda url, **kwargs: True,
    )
    session = browser.open_session(permission=policy, headless=True)
    query = BrowserTargetQuery(
        kind=BrowserTargetQueryKind.DOM_ID,
        value="select-target",
    )
    observed = browser.observe_target(session.session_id, query)
    return browser, session, policy, page, observed


def _action(session, observed, *, value="next"):
    return BrowserAction.create(
        session_id=session.session_id,
        page_id=observed.page_id,
        kind=BrowserActionKind.SELECT_OPTION,
        target=observed.target,
        args={"value": value},
    )


class ManagedBrowserSelectOptionTests(unittest.TestCase):
    def test_select_requires_page_interaction_permission_at_authority_boundary(self):
        permission = BrowserPermissionContext()
        browser, session, _permission, page, observed = _build(
            {"connected": True, "selected": "before"},
            permission=permission,
        )
        try:
            action = _action(session, observed)
            with self.assertRaisesRegex(ValueError, "not permitted"):
                BrowserActionAuthority.from_observation(action, observed, permission)
            self.assertEqual(page.select_dispatches, 0)
        finally:
            browser.close()

    def test_select_requires_explicit_string_value_before_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "selected": "before"}
        )
        try:
            action = BrowserAction.create(
                session_id=session.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.SELECT_OPTION,
                target=observed.target,
                args={},
            )
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("explicit string value", effect.error or "")
            self.assertEqual(page.select_dispatches, 0)
        finally:
            browser.close()

    def test_select_requires_native_select_target_before_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "selected": "before", "supported": False}
        )
        try:
            action = _action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("select/combobox", effect.error or "")
            self.assertEqual(page.select_dispatches, 0)
        finally:
            browser.close()

    def test_select_refuses_disabled_and_multiple_targets(self):
        for field, expected in (("disabled", "disabled"), ("multiple", "multi-select")):
            with self.subTest(field=field):
                browser, session, permission, page, observed = _build(
                    {"connected": True, "selected": "before", field: True}
                )
                try:
                    action = _action(session, observed)
                    authority = BrowserActionAuthority.from_observation(action, observed, permission)
                    effect = browser.act(action, authority)
                    self.assertFalse(effect.success)
                    self.assertIn(expected, effect.error or "")
                    self.assertEqual(page.select_dispatches, 0)
                finally:
                    browser.close()

    def test_select_refuses_already_selected_value_before_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "selected": "next"}
        )
        try:
            action = _action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("already selected", effect.error or "")
            self.assertEqual(page.select_dispatches, 0)
        finally:
            browser.close()

    def test_select_refuses_ambiguous_native_option_mapping_before_dispatch(self):
        cases = (
            (
                {"label": "Duplicate"},
                [
                    {"value": "a", "label": "Duplicate"},
                    {"value": "b", "label": "Duplicate"},
                ],
                "exactly one fresh native option",
            ),
            (
                {"value": "dup"},
                [
                    {"value": "dup", "label": "First"},
                    {"value": "dup", "label": "Second"},
                ],
                "exactly one fresh native option",
            ),
            (
                {"value": "b"},
                [
                    {"value": "a", "label": "Same label"},
                    {"value": "b", "label": "Same label"},
                ],
                "ambiguous visible option label",
            ),
        )
        for args, options, expected_error in cases:
            with self.subTest(args=args):
                browser, session, permission, page, observed = _build(
                    {
                        "connected": True,
                        "selected": "before",
                        "selected_label": "Before",
                        "options": [
                            {"value": "before", "label": "Before"},
                            *options,
                        ],
                    }
                )
                try:
                    action = BrowserAction.create(
                        session_id=session.session_id,
                        page_id=observed.page_id,
                        kind=BrowserActionKind.SELECT_OPTION,
                        target=observed.target,
                        args=args,
                    )
                    authority = BrowserActionAuthority.from_observation(
                        action, observed, permission
                    )
                    effect = browser.act(action, authority)
                    self.assertFalse(effect.success)
                    self.assertIn(expected_error, effect.error or "")
                    self.assertEqual(page.select_dispatches, 0)
                finally:
                    browser.close()

    def test_select_succeeds_only_from_fresh_same_node_selected_value(self):
        raw_requested = "ZN private option value"
        browser, session, permission, page, observed = _build(
            {"connected": True, "selected": "before"}
        )
        try:
            action = _action(session, observed, value=raw_requested)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_selected_value")
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertTrue(effect.data["selection_dispatched"])
            self.assertEqual(page.select_dispatches, 1)
            digest = hashlib.sha256(raw_requested.encode("utf-8")).hexdigest()
            self.assertEqual(effect.data["expected_value_sha256"], digest)
            self.assertEqual(effect.data["selected_value_sha256_after"], digest)
            self.assertEqual(effect.data["selected_value_length_after"], len(raw_requested))
            self.assertNotEqual(effect.observed_at, observed.captured_at)
            self.assertNotIn(raw_requested, json.dumps(effect.data, sort_keys=True))
        finally:
            browser.close()

    def test_select_by_visible_label_uses_fresh_same_node_label_evidence(self):
        raw_label = "Private Beta"
        browser, session, permission, page, observed = _build(
            {
                "connected": True,
                "selected": "alpha",
                "selected_label": "Alpha",
                "label_values": {raw_label: "beta-private"},
            }
        )
        try:
            action = BrowserAction.create(
                session_id=session.session_id,
                page_id=observed.page_id,
                kind=BrowserActionKind.SELECT_OPTION,
                target=observed.target,
                args={"label": raw_label},
            )
            authority = BrowserActionAuthority.from_observation(
                action, observed, permission
            )
            effect = browser.act(action, authority)
            self.assertTrue(effect.success, effect.error)
            self.assertEqual(effect.postcondition, "same_exact_target_selected_label")
            self.assertEqual(effect.data["selection_mode"], "label")
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertTrue(effect.data["selection_dispatched"])
            digest = hashlib.sha256(raw_label.encode("utf-8")).hexdigest()
            self.assertEqual(effect.data["expected_label_sha256"], digest)
            self.assertEqual(effect.data["selected_label_sha256_after"], digest)
            self.assertEqual(page.node["selected"], "beta-private")
            self.assertNotIn(raw_label, json.dumps(effect.data, sort_keys=True))
        finally:
            browser.close()

    def test_select_fails_if_provider_dispatch_does_not_change_selected_value(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "selected": "before", "select_blocked": True}
        )
        try:
            action = _action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("postcondition was not observed", effect.error or "")
            self.assertTrue(effect.data["exact_node_continuity"])
            self.assertEqual(page.select_dispatches, 1)
        finally:
            browser.close()

    def test_select_fails_if_same_shape_target_is_replaced_during_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "selected": "before", "replace_on_select": True}
        )
        try:
            action = _action(session, observed)
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("replaced target node", effect.error or "")
            self.assertFalse(effect.data["exact_node_continuity"])
            self.assertEqual(page.select_dispatches, 1)
        finally:
            browser.close()

    def test_select_rejects_control_characters_before_dispatch(self):
        browser, session, permission, page, observed = _build(
            {"connected": True, "selected": "before"}
        )
        try:
            action = _action(session, observed, value="bad\nvalue")
            authority = BrowserActionAuthority.from_observation(action, observed, permission)
            effect = browser.act(action, authority)
            self.assertFalse(effect.success)
            self.assertIn("control characters", effect.error or "")
            self.assertEqual(page.select_dispatches, 0)
        finally:
            browser.close()


if __name__ == "__main__":
    unittest.main()
