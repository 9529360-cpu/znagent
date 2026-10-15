"""M0-3: anti-hallucination ID mapping for structured model outputs."""

from __future__ import annotations

import unittest

from zn_agent.core.id_mapping import (
    IndexedReferences,
    is_uuid_shaped,
    resolve_structured_id_refs,
)
from zn_agent.core.output_contract import OutputContract

UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"
UUID_C = "33333333-3333-4333-8333-333333333333"
UUID_UPPER = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"


def _mapping() -> IndexedReferences:
    return IndexedReferences(
        entries=(
            (UUID_A, "old memory: user prefers concise replies"),
            (UUID_B, "old memory: project uses pytest"),
            (UUID_C, "old memory: deploy on Fridays is risky"),
        )
    )


class TestIsUuidShaped(unittest.TestCase):
    def test_canonical_uuid(self) -> None:
        self.assertTrue(is_uuid_shaped(UUID_A))
        self.assertTrue(is_uuid_shaped(UUID_UPPER))

    def test_braced_and_bare_hex(self) -> None:
        self.assertTrue(is_uuid_shaped("{" + UUID_A + "}"))
        self.assertTrue(is_uuid_shaped("a" * 32))

    def test_non_uuid(self) -> None:
        self.assertFalse(is_uuid_shaped("0"))
        self.assertFalse(is_uuid_shaped("[1]"))
        self.assertFalse(is_uuid_shaped("user prefers concise replies"))
        self.assertFalse(is_uuid_shaped(""))
        self.assertFalse(is_uuid_shaped(None))
        self.assertFalse(is_uuid_shaped(0))
        self.assertFalse(is_uuid_shaped("not-a-uuid"))


class TestIndexedReferences(unittest.TestCase):
    def test_render_hides_real_ids(self) -> None:
        rendered = _mapping().render()
        self.assertNotIn(UUID_A, rendered)
        self.assertNotIn(UUID_B, rendered)
        self.assertNotIn(UUID_C, rendered)
        self.assertIn("[0] old memory: user prefers concise replies", rendered)
        self.assertIn("[1] old memory: project uses pytest", rendered)
        self.assertIn("[2] old memory: deploy on Fridays is risky", rendered)
        self.assertIn("ONLY by their index numbers", rendered)

    def test_resolve_index_forms(self) -> None:
        mapping = _mapping()
        self.assertEqual(mapping.resolve(0).real_id, UUID_A)
        self.assertEqual(mapping.resolve("1").real_id, UUID_B)
        self.assertEqual(mapping.resolve(" 2 ").real_id, UUID_C)
        self.assertEqual(mapping.resolve("[0]").real_id, UUID_A)
        self.assertEqual(mapping.resolve("[ 1 ]").real_id, UUID_B)

    def test_resolve_uuid_is_rejected_even_when_real(self) -> None:
        # The model must never output IDs -- even a guessed-correct UUID
        # is rejected, not trusted. This is the core M0-3 guarantee.
        mapping = _mapping()
        for candidate in (
            UUID_A,
            UUID_UPPER,
            "{" + UUID_B + "}",
            "a" * 32,
            UUID_C.upper(),
        ):
            result = mapping.resolve(candidate)
            self.assertIsNone(result.real_id, candidate)
            self.assertIn("hallucinated", result.error or "")

    def test_resolve_invalid_refs(self) -> None:
        mapping = _mapping()
        for candidate in ("3", "99", "-1", "abc", "", "1.0", "+1", "1e0", None, 1.5, True, ["0"]):
            result = mapping.resolve(candidate)
            self.assertIsNone(result.real_id, repr(candidate))
            self.assertTrue(result.error, repr(candidate))

    def test_resolve_all_mixed(self) -> None:
        mapping = _mapping()
        resolved, errors = mapping.resolve_all(["0", UUID_B, "2", "7"])
        self.assertEqual(resolved, [UUID_A, UUID_C])
        self.assertEqual(len(errors), 2)
        # The bad refs never yield IDs.
        self.assertNotIn(UUID_B, resolved)

    def test_constructor_rejects_bad_entries(self) -> None:
        with self.assertRaises(ValueError):
            IndexedReferences(entries=(("", "empty id"),))
        with self.assertRaises(ValueError):
            IndexedReferences(entries=((UUID_A, "one"), (UUID_A, "dup"),))

    def test_empty_mapping_rejects_everything(self) -> None:
        mapping = IndexedReferences(entries=())
        self.assertEqual(len(mapping), 0)
        self.assertIsNone(mapping.resolve("0").real_id)
        self.assertIn("0 to -1", mapping.resolve("0").error or "")


class TestResolveStructuredIdRefs(unittest.TestCase):
    def test_single_and_list_fields(self) -> None:
        mapping = _mapping()
        resolved, errors = resolve_structured_id_refs(
            {"memory_ref": "1", "refs": ["0", "2"]},
            field_mappings={"memory_ref": mapping, "refs": mapping},
        )
        self.assertEqual(errors, [])
        self.assertEqual(resolved["memory_ref"], UUID_B)
        self.assertEqual(resolved["refs"], [UUID_A, UUID_C])

    def test_failed_field_left_unreplaced(self) -> None:
        mapping = _mapping()
        resolved, errors = resolve_structured_id_refs(
            {"memory_ref": UUID_A, "other": "keep me"},
            field_mappings={"memory_ref": mapping},
        )
        self.assertEqual(len(errors), 1)
        self.assertEqual(resolved["memory_ref"], UUID_A)  # untouched raw input
        self.assertEqual(resolved["other"], "keep me")

    def test_missing_field_skipped(self) -> None:
        resolved, errors = resolve_structured_id_refs(
            {}, field_mappings={"memory_ref": _mapping()}
        )
        self.assertEqual((resolved, errors), ({}, []))


class TestOutputContractIndexedIds(unittest.TestCase):
    def _contract(self) -> OutputContract:
        return OutputContract(
            top_level_key="selection",
            shape_example='{"selection": {"memory_ref": "0"}}',
            required_keys=("memory_ref",),
            field_types={"memory_ref": "str"},
            indexed_id_fields={"memory_ref": _mapping()},
        )

    def test_extract_then_resolve_then_validate(self) -> None:
        contract = self._contract()
        payload = contract.extract('{"selection": {"memory_ref": "2"}}')
        self.assertIsNotNone(payload)
        assert payload is not None
        resolved, errors = contract.resolve_ids(payload)
        self.assertEqual(errors, [])
        self.assertEqual(resolved["memory_ref"], UUID_C)
        self.assertEqual(contract.validate(resolved), [])

    def test_uuid_ref_rejected_not_trusted(self) -> None:
        contract = self._contract()
        payload = contract.extract(f'{{"selection": {{"memory_ref": "{UUID_A}"}}}}')
        assert payload is not None
        resolved, errors = contract.resolve_ids(payload)
        # One error reported: the caller must not use this field.
        self.assertEqual(len(errors), 1)
        self.assertIn("hallucinated", errors[0])
        # Field left unreplaced (raw input), never laundered into a trusted ID.
        self.assertEqual(resolved["memory_ref"], UUID_A)

    def test_no_indexed_fields_is_noop(self) -> None:
        contract = OutputContract(
            top_level_key="selection",
            shape_example='{"selection": {"note": "x"}}',
        )
        payload = {"note": "x"}
        resolved, errors = contract.resolve_ids(payload)
        self.assertEqual((resolved, errors), (payload, []))

    def test_contract_rejects_bad_indexed_field(self) -> None:
        with self.assertRaises(ValueError):
            OutputContract(
                top_level_key="selection",
                shape_example='{"selection": {}}',
                indexed_id_fields={"bad-name!": _mapping()},
            )
        with self.assertRaises(ValueError):
            OutputContract(
                top_level_key="selection",
                shape_example='{"selection": {}}',
                indexed_id_fields={"memory_ref": "not-a-mapping"},  # type: ignore[dict-item]
            )


if __name__ == "__main__":
    unittest.main()
