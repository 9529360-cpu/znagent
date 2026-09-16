from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from zn_agent.core.research_information_product_resident import (
    ProductResearchInformationResidentRuntime,
)
from zn_agent.core.user_browser_multi_record_result import (
    parse_verified_record_excerpts,
    requested_multi_record_count,
)


class UserBrowserMultiRecordResultTests(unittest.TestCase):
    def test_recognizes_only_explicit_small_recent_record_counts(self) -> None:
        self.assertEqual(requested_multi_record_count("查 Alice 最近三笔订单，把状态告诉我"), 3)
        self.assertEqual(requested_multi_record_count("show me the latest 4 order records"), 4)
        self.assertEqual(requested_multi_record_count("看看最近两条记录"), 2)
        self.assertIsNone(requested_multi_record_count("查 Alice 的订单状态"))
        self.assertIsNone(requested_multi_record_count("查最近十笔订单"))
        self.assertIsNone(requested_multi_record_count("最近两笔订单和最近三笔订单"))

    def test_accepts_distinct_verbatim_records_in_source_order(self) -> None:
        context = (
            "客户 alice@example.test 最近三笔订单 "
            "订单 #ZN-733 | 2026-09-15 | 状态: 已发货 "
            "订单 #ZN-732 | 2026-09-14 | 状态: 处理中 "
            "订单 #ZN-731 | 2026-09-13 | 状态: 已完成"
        )
        records = [
            "订单 #ZN-733 | 2026-09-15 | 状态: 已发货",
            "订单 #ZN-732 | 2026-09-14 | 状态: 处理中",
            "订单 #ZN-731 | 2026-09-13 | 状态: 已完成",
        ]
        parsed = parse_verified_record_excerpts(
            json.dumps({"status": "verified", "records": records}, ensure_ascii=False),
            context=context,
            expected_count=3,
        )
        self.assertEqual(parsed, tuple(records))

    def test_rejects_wrong_count_reorder_duplicates_or_invented_text(self) -> None:
        context = "A-one B-two C-three"
        cases = [
            {"status": "verified", "records": ["A-one", "B-two"]},
            {"status": "verified", "records": ["B-two", "A-one", "C-three"]},
            {"status": "verified", "records": ["A-one", "A-one", "C-three"]},
            {"status": "verified", "records": ["A-one", "B-two", "D-four"]},
            {"status": "not_verified", "records": []},
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertIsNone(
                    parse_verified_record_excerpts(
                        json.dumps(value),
                        context=context,
                        expected_count=3,
                    )
                )

    @staticmethod
    def _product_runtime_with_authorization(*, authorized: bool):
        resident = ProductResearchInformationResidentRuntime.__new__(
            ProductResearchInformationResidentRuntime
        )
        resident.user_browser_authorization = lambda: {
            "authorized": authorized,
            "plane": "user",
            "browser_ownership": "user",
            "authorization_scope": "explicit_current_tab",
        }
        return resident

    def test_existing_session_record_lookup_admission_requires_explicit_current_tab_authority(self) -> None:
        event = SimpleNamespace(
            kind="desktop_user_event",
            task="去我已经登录的系统里查 Alice 最近三笔订单，把状态告诉我。",
            payload={},
        )
        admitted = self._product_runtime_with_authorization(authorized=True)
        self.assertTrue(admitted._is_explicit_existing_session_record_lookup(event))

        unauthorized = self._product_runtime_with_authorization(authorized=False)
        self.assertFalse(unauthorized._is_explicit_existing_session_record_lookup(event))

    def test_existing_session_record_lookup_admission_does_not_make_system_a_global_browser_synonym(self) -> None:
        resident = self._product_runtime_with_authorization(authorized=True)
        rejected_tasks = (
            "去我已经登录的系统里打开报表。",
            "去系统里查 Alice 最近三笔订单，把状态告诉我。",
            "去我已经登录的系统里查 Alice 的订单状态。",
            "去我已经登录的软件里查 Alice 最近三笔订单，把状态告诉我。",
        )
        for task in rejected_tasks:
            with self.subTest(task=task):
                event = SimpleNamespace(
                    kind="desktop_user_event",
                    task=task,
                    payload={},
                )
                self.assertFalse(resident._is_explicit_existing_session_record_lookup(event))


if __name__ == "__main__":
    unittest.main()
