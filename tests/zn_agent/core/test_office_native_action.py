from __future__ import annotations

import unittest

from zn_agent.core.office_native_action import (
    normalize_cell_address,
    normalize_office_kind,
    normalize_worksheet_name,
    scalar_digest,
    text_sha256,
)


class OfficeNativeActionContractTests(unittest.TestCase):
    def test_normalizes_supported_office_process_names(self) -> None:
        self.assertEqual(normalize_office_kind("WINWORD.EXE"), "word")
        self.assertEqual(normalize_office_kind("excel.exe"), "excel")
        self.assertEqual(normalize_office_kind("POWERPNT.EXE"), "powerpoint")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            normalize_office_kind("notepad.exe")

    def test_excel_address_is_one_bounded_a1_cell(self) -> None:
        self.assertEqual(normalize_cell_address("$b$2"), "B2")
        self.assertEqual(normalize_cell_address("XFD1048576"), "XFD1048576")
        for value in ("A0", "XFE1", "A1048577", "A1:B2", "R1C1", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_cell_address(value)

    def test_worksheet_name_is_bounded(self) -> None:
        self.assertEqual(normalize_worksheet_name(" Sheet1 "), "Sheet1")
        with self.assertRaises(ValueError):
            normalize_worksheet_name("")
        with self.assertRaises(ValueError):
            normalize_worksheet_name("x" * 32)

    def test_scalar_digest_is_stable_and_privacy_safe(self) -> None:
        secret = "sensitive spreadsheet value"
        digest = scalar_digest(secret)
        self.assertEqual(digest["value_kind"], "text")
        self.assertEqual(digest["value_chars"], len(secret))
        self.assertEqual(digest["value_sha256"], text_sha256(secret))
        self.assertNotIn(secret, repr(digest))
        self.assertEqual(scalar_digest(42), scalar_digest(42.0))
        self.assertNotEqual(scalar_digest(True), scalar_digest(1))

    def test_scalar_digest_rejects_non_scalar_and_non_finite(self) -> None:
        for value in ([1], {"a": 1}, float("inf"), float("nan")):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    scalar_digest(value)


if __name__ == "__main__":
    unittest.main()
