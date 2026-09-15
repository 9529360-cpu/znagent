from __future__ import annotations

import json
import unittest

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


if __name__ == "__main__":
    unittest.main()
