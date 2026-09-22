from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.browser import BrowserPermissionContext
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.research_managed_browser import ResearchSemanticPlaywrightManagedBrowser
from zn_agent.core.user_browser_managed_research_resident import (
    UserBrowserManagedResearchResidentRuntime,
)


class UserBrowserManagedResearchResidentTests(unittest.TestCase):
    def test_normal_language_reference_research_is_recognized_without_engineering_targets(self) -> None:
        event = SimpleNamespace(
            task="检查这里链接的两个参考页，确认它们一致的 release code，然后回来在这个页面搜索那个 code。",
            payload={"model_policy": "never"},
        )
        self.assertTrue(
            UserBrowserManagedResearchResidentRuntime._natural_managed_reference_search(event)
        )

    def test_reference_ranking_keeps_multiple_reasonable_sources(self) -> None:
        ranked = UserBrowserManagedResearchResidentRuntime._rank_reference_candidates(
            [
                {"href": "https://example.test/other", "text": "Other"},
                {"href": "https://example.test/release-note", "text": "Reference release note"},
                {"href": "https://example.test/registry", "text": "Reference release registry"},
            ]
        )
        self.assertGreaterEqual(len(ranked), 2)
        self.assertEqual(
            {item["href"] for item in ranked[:2]},
            {
                "https://example.test/release-note",
                "https://example.test/registry",
            },
        )

    def test_release_code_extraction_is_phrase_grounded_not_fixture_specific(self) -> None:
        self.assertEqual(
            UserBrowserManagedResearchResidentRuntime._release_code(
                "Confirmed release code: BUILD-91A7F"
            ),
            "BUILD-91A7F",
        )
        self.assertEqual(
            UserBrowserManagedResearchResidentRuntime._release_code(
                "Registry release code: X9.2026-09"
            ),
            "X9.2026-09",
        )
        self.assertIsNone(
            UserBrowserManagedResearchResidentRuntime._release_code(
                "release code: ONE and release code: TWO"
            )
        )

    def test_detail_replan_can_choose_one_of_multiple_same_origin_links(self) -> None:
        candidates = UserBrowserManagedResearchResidentRuntime._detail_candidates(
            {
                "links": [
                    {"href": "https://source.test/help", "text": "Help"},
                    {"href": "https://source.test/release/details", "text": "View release details"},
                    {"href": "https://source.test/release/archive", "text": "Version archive"},
                    {"href": "https://other.test/release/details", "text": "External details"},
                ]
            },
            "https://source.test/release",
        )
        self.assertIn("https://source.test/release/details", candidates)
        self.assertGreaterEqual(len(candidates), 2)
        self.assertNotIn("https://other.test/release/details", candidates)

    def test_same_origin_reference_urls_are_deduplicated_before_permission(self) -> None:
        urls = (
            "http://127.0.0.1:8123/ref-a",
            "http://127.0.0.1:8123/ref-b",
            "https://other.test/ref-c",
        )
        origins = tuple(
            dict.fromkeys(
                UserBrowserManagedResearchResidentRuntime._origin_url(url) for url in urls
            )
        )
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_private_network=True,
            allowed_origins=origins,
        )
        self.assertEqual(len(permission.allowed_origins), 2)

    def test_research_browser_accepts_capability_not_playwright_type(self) -> None:
        resident = object.__new__(UserBrowserManagedResearchResidentRuntime)
        fake = SimpleNamespace(read_page=lambda *_args, **_kwargs: {})
        resident.research_browser = fake
        self.assertIs(resident._managed_research_browser(), fake)

    def test_final_resident_composition_separates_interactive_and_readable_managed_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(
                    resident,
                    UserBrowserManagedResearchResidentRuntime,
                )
                self.assertIsInstance(
                    resident.managed_browser,
                    ResearchSemanticPlaywrightManagedBrowser,
                )
                self.assertTrue(callable(getattr(resident.research_browser, "read_page", None)))
                self.assertIsNot(resident.research_browser, resident.managed_browser)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
