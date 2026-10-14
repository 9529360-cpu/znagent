from __future__ import annotations

import io
import logging
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.config import load_zn_config, save_zn_config
from zn_agent.core.credential_isolation import (
    CredentialRedactingFilter,
    CredentialValueDetected,
    check_no_credential_value,
    contains_credential_value,
    is_credential_reference,
    mint_credential_reference,
    redact_for_log,
)
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.store import KernelStore

# Obviously fake test-only values. These are not real credentials; they only
# carry the *shape* of one so the interception can be proven.
FAKE_SK = "sk-test-fake-abcdefghij12345678"
FAKE_BEARER = "Bearer test-fake-bearer-token-value"
FAKE_JWT = "eyJ0ZXN0LWZha2UtdG9rZW4xMjM0NTY3OA.eyJ0ZXN0LWZha2UtdG9rZW4xMjM0NTY3OA.eyJ0ZXN0LWZha2UtdG9rZW4xMjM0NTY3OA"
FAKE_GITHUB = "ghp_testfake0000000000000000000000000000"


class CredentialReferenceTests(unittest.TestCase):
    def test_minted_reference_is_opaque_and_not_the_value(self) -> None:
        first = mint_credential_reference("openai")
        second = mint_credential_reference("openai")

        self.assertTrue(is_credential_reference(first))
        self.assertTrue(is_credential_reference(second))
        self.assertNotEqual(first, second)
        self.assertNotIn(FAKE_SK, first)
        self.assertTrue(first.startswith("credential:openai:"))

    def test_provider_reference_is_a_reference_not_a_value(self) -> None:
        self.assertTrue(is_credential_reference("provider:openai"))
        self.assertFalse(is_credential_reference(FAKE_SK))
        self.assertFalse(is_credential_reference("not a reference"))

    def test_mint_rejects_bad_kind(self) -> None:
        with self.assertRaises(ValueError):
            mint_credential_reference("has space")
        with self.assertRaises(ValueError):
            mint_credential_reference("")

    def test_reference_values_pass_the_write_check(self) -> None:
        check_no_credential_value(mint_credential_reference("openai"), where="test")
        check_no_credential_value({"credential_ref": "provider:openai"}, where="test")
        check_no_credential_value("provider:openai", where="test")


class CredentialDetectionTests(unittest.TestCase):
    def test_credential_shapes_are_detected(self) -> None:
        for shaped in (
            FAKE_SK,
            f"api_key={FAKE_SK}",
            f"password='{FAKE_SK}'",
            FAKE_BEARER,
            FAKE_JWT,
            FAKE_GITHUB,
            "https://user:test-fake-pass@example.test/v1",
            "https://example.test/v1?access_token=test-fake-query-secret",
            {"model": {"api_key": FAKE_SK}},
            ["token=" + FAKE_SK],
        ):
            with self.subTest(shaped=str(shaped)[:40]):
                self.assertTrue(contains_credential_value(shaped))

    def test_ordinary_text_is_not_detected(self) -> None:
        for plain in (
            "my favorite color is blue",
            "token bucket algorithm limits request rate",
            "password policy requires rotation every 90 days",
            "the api key concept was explained in class",
            "provider:openai",
            "",
            42,
            {"key": "value"},
        ):
            with self.subTest(plain=str(plain)[:40]):
                self.assertFalse(contains_credential_value(plain))

    def test_check_raises_without_leaking_the_value(self) -> None:
        with self.assertRaises(CredentialValueDetected) as caught:
            check_no_credential_value(f"api_key={FAKE_SK}", where="test:boundary")
        self.assertNotIn(FAKE_SK, str(caught.exception))
        self.assertIn("test:boundary", str(caught.exception))


class MemoryWriteInterceptionTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = KernelStore(Path(tmp.name) / "kernel.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_memory_rejects_credential_shaped_value(self) -> None:
        with self.assertRaises(CredentialValueDetected):
            self.memory.remember("openai key", f"api_key={FAKE_SK}")
        self.assertIsNone(self.store.get_fact("openai key"))
        self.assertEqual(self.store.list_facts(), [])

    def test_memory_rejects_bare_token_value(self) -> None:
        with self.assertRaises(CredentialValueDetected):
            self.memory.remember("provider token", FAKE_SK)
        self.assertEqual(self.store.list_facts(), [])

    def test_memory_rejects_credential_shaped_alias(self) -> None:
        with self.assertRaises(CredentialValueDetected):
            self.memory.remember("plain key", "plain value", aliases=(FAKE_SK,))
        self.assertEqual(self.store.list_facts(), [])

    def test_memory_accepts_opaque_reference_value(self) -> None:
        reference = mint_credential_reference("openai")
        self.memory.remember("openai credential", reference)
        self.assertEqual(self.store.get_fact("openai credential"), reference)

    def test_memory_accepts_ordinary_facts(self) -> None:
        self.memory.remember("reply language", "Chinese")
        self.assertEqual(self.store.get_fact("reply language"), "Chinese")


class ConfigFileWriteInterceptionTests(unittest.TestCase):
    def test_config_rejects_inline_api_key_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            with self.assertRaises(CredentialValueDetected):
                save_zn_config({"model": {"api_key": FAKE_SK}}, path)
            self.assertFalse(path.exists())

    def test_config_rejects_bearer_value_in_nested_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            with self.assertRaises(CredentialValueDetected):
                save_zn_config(
                    {"zn_kernel": {"routes": [{"authorization": FAKE_BEARER}]}},
                    path,
                )
            self.assertFalse(path.exists())

    def test_config_accepts_credential_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            save_zn_config(
                {"model": {"provider": "openai", "credential_ref": "provider:openai"}},
                path,
            )
            saved = load_zn_config(path)
            self.assertEqual(saved["model"]["credential_ref"], "provider:openai")
            self.assertNotIn(FAKE_SK, path.read_text(encoding="utf-8"))


class LogRedactionTests(unittest.TestCase):
    def test_redact_for_log_removes_credential_value_keeps_context(self) -> None:
        scrubbed = redact_for_log(f"provider rejected request; api_key={FAKE_SK}")

        self.assertNotIn(FAKE_SK, scrubbed)
        self.assertIn("provider rejected request", scrubbed)
        self.assertIn("<redacted>", scrubbed)

    def test_redact_for_log_covers_bearer_jwt_and_url(self) -> None:
        raw = (
            f"Authorization: {FAKE_BEARER} key {FAKE_JWT} "
            "url=https://user:test-fake-pass@example.test/v1"
        )
        scrubbed = redact_for_log(raw)

        self.assertNotIn("test-fake-bearer-token-value", scrubbed)
        self.assertNotIn(FAKE_JWT, scrubbed)
        self.assertNotIn("test-fake-pass", scrubbed)

    def test_logging_filter_scrubs_format_args_before_output(self) -> None:
        stream = io.StringIO()
        logger = logging.getLogger("zn_agent.test.credential_isolation")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        handler = logging.StreamHandler(stream)
        handler.addFilter(CredentialRedactingFilter())
        logger.addHandler(handler)
        try:
            logger.warning("call failed: api_key=%s", FAKE_SK)
            logger.warning("plain message without secrets")
        finally:
            logger.removeHandler(handler)

        output = stream.getvalue()
        self.assertNotIn(FAKE_SK, output)
        self.assertIn("plain message without secrets", output)
        self.assertIn("<redacted>", output)


if __name__ == "__main__":
    unittest.main()
