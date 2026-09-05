from __future__ import annotations

import unittest

from zn_agent.core.structured_cognition import decode_structured_cognition_object


class StructuredCognitionEnvelopeTests(unittest.TestCase):
    def test_accepts_raw_json_object(self) -> None:
        self.assertEqual(
            decode_structured_cognition_object('{"kind":"demo","value":1}'),
            {"kind": "demo", "value": 1},
        )

    def test_accepts_single_json_fence(self) -> None:
        self.assertEqual(
            decode_structured_cognition_object(
                '```json\n{"kind":"demo","items":["a","b"]}\n```'
            ),
            {"kind": "demo", "items": ["a", "b"]},
        )

    def test_accepts_single_unlabelled_fence(self) -> None:
        self.assertEqual(
            decode_structured_cognition_object('```\n{"kind":"demo"}\n```'),
            {"kind": "demo"},
        )

    def test_rejects_surrounding_prose(self) -> None:
        self.assertIsNone(
            decode_structured_cognition_object(
                'Here is the result:\n```json\n{"kind":"demo"}\n```'
            )
        )
        self.assertIsNone(
            decode_structured_cognition_object(
                '```json\n{"kind":"demo"}\n```\nDone.'
            )
        )

    def test_rejects_multiple_or_nested_fences(self) -> None:
        self.assertIsNone(
            decode_structured_cognition_object(
                '```json\n{"kind":"one"}\n```\n```json\n{"kind":"two"}\n```'
            )
        )
        self.assertIsNone(
            decode_structured_cognition_object(
                '```json\n{"kind":"one"}\n```oops\n```'
            )
        )

    def test_rejects_non_object_and_trailing_json(self) -> None:
        self.assertIsNone(decode_structured_cognition_object('[1, 2, 3]'))
        self.assertIsNone(
            decode_structured_cognition_object('{"kind":"one"} {"kind":"two"}')
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
