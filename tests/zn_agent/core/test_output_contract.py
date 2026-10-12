from __future__ import annotations

import unittest

from zn_agent.core.output_contract import OutputContract


def _contract() -> OutputContract:
    return OutputContract(
        top_level_key="zn_result",
        shape_example='{"zn_result":{"items":["a"],"count":2}}',
        required_keys=("items",),
        field_types={"items": "list", "count": "int"},
    )


class ContractConstructionTests(unittest.TestCase):
    def test_bad_key_fails_fast(self):
        with self.assertRaises(ValueError):
            OutputContract(top_level_key="bad key!", shape_example='{"a":{}}')

    def test_bad_shape_fails_fast(self):
        with self.assertRaises(ValueError):
            OutputContract(top_level_key="a", shape_example='not json')

    def test_shape_missing_key_fails_fast(self):
        with self.assertRaises(ValueError):
            OutputContract(top_level_key="a", shape_example='{"b":{}}')

    def test_unknown_dtype_fails_fast(self):
        with self.assertRaises(ValueError):
            OutputContract(
                top_level_key="a",
                shape_example='{"a":{}}',
                field_types={"x": "datetime"},
            )

    def test_instruction_is_stable(self):
        first = _contract().instruction()
        second = _contract().instruction()
        self.assertEqual(first, second)
        self.assertIn("zn_result", first)
        self.assertIn("Return ONLY", first)


class ContractExtractTests(unittest.TestCase):
    def test_strict_json(self):
        payload = _contract().extract('{"zn_result":{"items":["a"],"count":2}}')
        self.assertEqual(payload, {"items": ["a"], "count": 2})

    def test_wrong_top_key_returns_none(self):
        self.assertIsNone(_contract().extract('{"other":{"items":[]}}'))

    def test_prose_wrapped_salvage(self):
        text = 'Here you go:\n{"zn_result": {"items": ["x", "y"], "count": 2}}\nDone.'
        payload = _contract().extract(text)
        self.assertEqual(payload, {"items": ["x", "y"], "count": 2})

    def test_salvage_balanced_braces(self):
        text = 'prefix {"zn_result": {"items": ["a{b}c"]}} suffix'
        payload = _contract().extract(text)
        self.assertEqual(payload, {"items": ["a{b}c"]})

    def test_garbage_returns_none(self):
        self.assertIsNone(_contract().extract("no json here at all"))


class ContractValidateTests(unittest.TestCase):
    def test_valid_payload(self):
        self.assertEqual(_contract().validate({"items": ["a"], "count": 2}), [])

    def test_missing_required(self):
        violations = _contract().validate({"count": 2})
        self.assertTrue(any("items" in v for v in violations))

    def test_wrong_dtype(self):
        violations = _contract().validate({"items": "not-a-list", "count": 2})
        self.assertTrue(any("list" in v for v in violations))

    def test_bool_is_not_int(self):
        violations = _contract().validate({"items": [], "count": True})
        self.assertTrue(any("count" in v for v in violations))

    def test_optional_field_skipped_when_absent(self):
        self.assertEqual(_contract().validate({"items": []}), [])


if __name__ == "__main__":
    unittest.main()
