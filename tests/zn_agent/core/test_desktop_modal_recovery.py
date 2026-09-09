from __future__ import annotations

import unittest
from dataclasses import replace

from zn_agent.core.desktop_modal_recovery_behavior import MAX_DESKTOP_MODAL_RECOVERY_OBSERVATIONS
from zn_agent.core.modal_window_sense import (
    ModalButtonObservation,
    ModalWindowObservation,
    NativeModalWindowSense,
    ParentWindowRecoveryObservation,
    WINDOW_INTERACTION_BLOCKED_BY_MODAL,
    WINDOW_INTERACTION_READY,
    modal_action_still_current,
    select_safe_modal_action,
)


PARENT_HWND = 1001
DIALOG_HWND = 1002
PID = 4242
PROCESS = "orders.exe"


def _button(
    name: str = "稍后继续",
    *,
    runtime_id: tuple[int, ...] = (42, 7),
    dialog_hwnd: int = DIALOG_HWND,
    process_id: int = PID,
) -> ModalButtonObservation:
    return ModalButtonObservation(
        runtime_id=runtime_id,
        dialog_hwnd=dialog_hwnd,
        process_id=process_id,
        name=name,
        class_name="Button",
        is_enabled=True,
        is_offscreen=False,
        center_x_fraction=0.4,
        center_y_fraction=0.6,
    )


def _modal(
    *,
    buttons: tuple[ModalButtonObservation, ...] | None = None,
    title: str = "更新提示",
    text_names: tuple[str, ...] = ("有可用更新。当前工作可以稍后继续。",),
    password: bool = False,
) -> ModalWindowObservation:
    return ModalWindowObservation(
        dialog_hwnd=DIALOG_HWND,
        dialog_process_id=PID,
        dialog_process_name=PROCESS,
        dialog_title=title,
        dialog_class_name="#32770",
        parent_hwnd=PARENT_HWND,
        parent_process_id=PID,
        parent_title="订单处理",
        owner_hwnd=PARENT_HWND,
        root_owner_hwnd=DIALOG_HWND,
        parent_root_owner_hwnd=PARENT_HWND,
        is_modal=True,
        dialog_interaction_state=WINDOW_INTERACTION_READY,
        parent_interaction_state=WINDOW_INTERACTION_BLOCKED_BY_MODAL,
        dialog_visible=True,
        dialog_enabled=True,
        contains_password_edit=password,
        text_names=text_names,
        buttons=buttons if buttons is not None else (_button(), _button("立即更新", runtime_id=(42, 8))),
        captured_at="2026-09-09T00:00:00Z",
    )


class DesktopModalSenseTests(unittest.TestCase):
    def test_exact_owned_modal_with_blocked_parent_is_admitted(self) -> None:
        observation = _modal()
        sense = NativeModalWindowSense(probe_fn=lambda hwnd, pid, name: observation)
        self.assertEqual(
            sense.probe(
                parent_hwnd=PARENT_HWND,
                parent_process_id=PID,
                parent_process_name=PROCESS,
            ),
            observation,
        )

    def test_is_modal_false_is_rejected(self) -> None:
        sense = NativeModalWindowSense(probe_fn=lambda *_: replace(_modal(), is_modal=False))
        with self.assertRaisesRegex(ValueError, "exact blocking parent relationship"):
            sense.probe(parent_hwnd=PARENT_HWND, parent_process_id=PID, parent_process_name=PROCESS)

    def test_parent_must_be_blocked_by_modal_window(self) -> None:
        sense = NativeModalWindowSense(
            probe_fn=lambda *_: replace(_modal(), parent_interaction_state=WINDOW_INTERACTION_READY)
        )
        with self.assertRaises(ValueError):
            sense.probe(parent_hwnd=PARENT_HWND, parent_process_id=PID, parent_process_name=PROCESS)

    def test_cross_process_dialog_is_rejected(self) -> None:
        observation = replace(_modal(), dialog_process_id=9999, dialog_process_name="installer.exe")
        sense = NativeModalWindowSense(probe_fn=lambda *_: observation)
        with self.assertRaises(ValueError):
            sense.probe(parent_hwnd=PARENT_HWND, parent_process_id=PID, parent_process_name=PROCESS)

    def test_direct_owner_must_be_exact_parent(self) -> None:
        sense = NativeModalWindowSense(probe_fn=lambda *_: replace(_modal(), owner_hwnd=777))
        with self.assertRaises(ValueError):
            sense.probe(parent_hwnd=PARENT_HWND, parent_process_id=PID, parent_process_name=PROCESS)

    def test_root_owner_identity_must_exist_and_remain_stable(self) -> None:
        sense = NativeModalWindowSense(probe_fn=lambda *_: replace(_modal(), root_owner_hwnd=0))
        with self.assertRaises(ValueError):
            sense.probe(parent_hwnd=PARENT_HWND, parent_process_id=PID, parent_process_name=PROCESS)
        admitted = _modal()
        fresh = replace(admitted, root_owner_hwnd=9999)
        self.assertFalse(modal_action_still_current(admitted, admitted.buttons[0], fresh, fresh.buttons[0]))

    def test_button_must_belong_to_exact_dialog_subtree(self) -> None:
        observation = _modal(buttons=(_button(dialog_hwnd=8888),))
        sense = NativeModalWindowSense(probe_fn=lambda *_: observation)
        with self.assertRaisesRegex(ValueError, "containment"):
            sense.probe(parent_hwnd=PARENT_HWND, parent_process_id=PID, parent_process_name=PROCESS)

    def test_exact_parent_recovery_requires_exact_dialog_absence_and_never_transfers_identity(self) -> None:
        good = ParentWindowRecoveryObservation(
            parent_hwnd=PARENT_HWND,
            parent_process_id=PID,
            parent_process_name=PROCESS,
            parent_title="订单处理",
            parent_class_name="WindowsForms10.Window",
            parent_interaction_state=WINDOW_INTERACTION_READY,
            dismissed_dialog_hwnd=DIALOG_HWND,
            dismissed_dialog_exists=False,
            visible=True,
            enabled=True,
            foreground=True,
            modal_absent=True,
            wait_for_input_idle=True,
            captured_at="2026-09-09T00:00:01Z",
        )
        sense = NativeModalWindowSense(
            probe_fn=lambda *_: None,
            parent_recovery_probe_fn=lambda *_: good,
        )
        self.assertEqual(
            sense.probe_parent_recovery(
                parent_hwnd=PARENT_HWND,
                parent_process_id=PID,
                parent_process_name=PROCESS,
                dismissed_dialog_hwnd=DIALOG_HWND,
            ),
            good,
        )
        replaced_parent = NativeModalWindowSense(
            probe_fn=lambda *_: None,
            parent_recovery_probe_fn=lambda *_: replace(good, parent_hwnd=9999),
        )
        with self.assertRaisesRegex(ValueError, "authority"):
            replaced_parent.probe_parent_recovery(
                parent_hwnd=PARENT_HWND,
                parent_process_id=PID,
                parent_process_name=PROCESS,
                dismissed_dialog_hwnd=DIALOG_HWND,
            )
        wrong_dialog = NativeModalWindowSense(
            probe_fn=lambda *_: None,
            parent_recovery_probe_fn=lambda *_: replace(good, dismissed_dialog_hwnd=8888),
        )
        with self.assertRaisesRegex(ValueError, "authority"):
            wrong_dialog.probe_parent_recovery(
                parent_hwnd=PARENT_HWND,
                parent_process_id=PID,
                parent_process_name=PROCESS,
                dismissed_dialog_hwnd=DIALOG_HWND,
            )


class DesktopModalSafetyClassificationTests(unittest.TestCase):
    def test_one_explicit_defer_continue_action_is_safe(self) -> None:
        action, failure = select_safe_modal_action(
            _modal(), user_goal="把订单编号拿到当前软件里找到对应记录。"
        )
        self.assertIsNone(failure)
        self.assertIsNotNone(action)
        self.assertEqual(action.name, "稍后继续")

    def test_duplicate_safe_semantics_fail_closed(self) -> None:
        observation = _modal(
            buttons=(
                _button("稍后继续", runtime_id=(42, 7)),
                _button("继续工作", runtime_id=(42, 8)),
            )
        )
        action, failure = select_safe_modal_action(observation, user_goal="继续当前订单任务。")
        self.assertIsNone(action)
        self.assertIn("exactly one", failure or "")

    def test_plain_later_plus_install_now_is_too_ambiguous_for_first_slice(self) -> None:
        observation = _modal(
            buttons=(
                _button("稍后", runtime_id=(42, 7)),
                _button("立即安装", runtime_id=(42, 8)),
            )
        )
        action, _ = select_safe_modal_action(observation, user_goal="继续订单任务。")
        self.assertIsNone(action)

    def test_save_discard_business_decision_is_rejected(self) -> None:
        observation = _modal(
            title="是否保存更改",
            text_names=("关闭前要保存更改吗？",),
            buttons=(
                _button("保存", runtime_id=(42, 7)),
                _button("不保存", runtime_id=(42, 8)),
                _button("取消", runtime_id=(42, 9)),
            ),
        )
        action, failure = select_safe_modal_action(observation, user_goal="继续订单任务。")
        self.assertIsNone(action)
        self.assertIn("decision", failure or "")

    def test_password_or_credential_modal_is_rejected(self) -> None:
        action, failure = select_safe_modal_action(_modal(password=True), user_goal="继续订单任务。")
        self.assertIsNone(action)
        self.assertIn("password", failure or "")

    def test_update_now_is_never_the_safe_action(self) -> None:
        action, _ = select_safe_modal_action(
            _modal(buttons=(_button("立即更新"),)), user_goal="继续订单任务。"
        )
        self.assertIsNone(action)


class DesktopModalFreshAuthorityTests(unittest.TestCase):
    def test_stale_modal_button_runtime_id_is_rejected(self) -> None:
        admitted = _modal()
        fresh = replace(
            admitted,
            buttons=(
                _button("稍后继续", runtime_id=(99, 1)),
                _button("立即更新", runtime_id=(99, 2)),
            ),
            captured_at="2026-09-09T00:00:02Z",
        )
        self.assertFalse(
            modal_action_still_current(admitted, admitted.buttons[0], fresh, fresh.buttons[0])
        )

    def test_same_exact_modal_button_authority_remains_current(self) -> None:
        admitted = _modal()
        fresh = replace(admitted, captured_at="2026-09-09T00:00:02Z")
        self.assertTrue(
            modal_action_still_current(admitted, admitted.buttons[0], fresh, fresh.buttons[0])
        )

    def test_recovery_polling_is_bounded(self) -> None:
        self.assertGreater(MAX_DESKTOP_MODAL_RECOVERY_OBSERVATIONS, 1)
        self.assertLessEqual(MAX_DESKTOP_MODAL_RECOVERY_OBSERVATIONS, 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
