from __future__ import annotations

import unittest

from zn_agent.core.research_information_work import (
    MAX_SELECTED_SOURCES,
    MAX_SOURCE_TEXT_CHARS,
    MAX_TOTAL_EVIDENCE_CHARS,
    ResearchBundle,
    apply_verified_synthesis,
    build_source_observation,
    canonical_source_url,
    dedupe_source_observations,
    evidence_pack,
    independent_read_sources,
    research_completion_errors,
    source_identity,
)
from zn_agent.core.web_resource import WebDocument, WebSearchItem


class ResearchInformationWorkTests(unittest.TestCase):
    def _source(self, url: str, content: str, *, provider: str = "fixture", published: str | None = None):
        metadata = {"provider": provider, "sourceURL": url}
        if published is not None:
            metadata["published_date"] = published
        return build_source_observation(
            WebSearchItem(title=url.rsplit("/", 1)[-1], url=url, position=1, metadata=metadata),
            WebDocument(url=url, title="Source", content=content, metadata=metadata),
            captured_at="2026-09-10T10:00:00+00:00",
        )

    def _failed_source(self, url: str, error: str = "timeout"):
        return build_source_observation(
            WebSearchItem(title="failed", url=url, position=1, metadata={"provider": "fixture"}),
            WebDocument(url=url, error=error, metadata={"provider": "fixture", "sourceURL": url}),
        )

    def test_canonical_identity_dedupes_tracking_variants_and_provider_duplicates(self) -> None:
        left = self._source("https://example.com/pricing?utm_source=exa", "Alpha price is $99.", provider="exa")
        right = self._source("https://example.com/pricing#price", "Alpha price is $99.", provider="tavily")
        merged = dedupe_source_observations([left, right])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].canonical_url, "https://example.com/pricing")
        self.assertEqual(set(merged[0].providers), {"exa", "tavily"})
        self.assertEqual(merged[0].source_id, source_identity("https://example.com/pricing"))

    def test_redirect_identity_preserves_requested_and_observed_url_but_rejects_cross_host_drift(self) -> None:
        candidate = WebSearchItem(title="redirect", url="https://example.com/old", position=1)
        same_host = build_source_observation(
            candidate,
            WebDocument(
                url="https://example.com/new",
                content="Current policy applies.",
                metadata={"requestedURL": "https://example.com/old", "sourceURL": "https://example.com/new", "provider": "fixture"},
            ),
        )
        self.assertEqual(same_host.extraction_status, "read")
        self.assertEqual(same_host.requested_url, "https://example.com/old")
        self.assertEqual(same_host.observed_url, "https://example.com/new")

        cross_host = build_source_observation(
            candidate,
            WebDocument(
                url="https://other.example/new",
                content="Different page.",
                metadata={"requestedURL": "https://example.com/old", "sourceURL": "https://other.example/new", "provider": "fixture"},
            ),
        )
        self.assertEqual(cross_host.extraction_status, "identity_mismatch")
        self.assertFalse(cross_host.evidence_text)

    def test_freshness_is_preserved_and_unknown_never_invents_publish_time(self) -> None:
        known = self._source("https://a.example/news", "Observed trend.", published="2026-09-09")
        unknown = self._source("https://b.example/news", "Observed trend.")
        self.assertEqual(known.published_at, "2026-09-09")
        self.assertEqual(known.freshness_status, "published")
        self.assertIsNone(unknown.published_at)
        self.assertEqual(unknown.freshness_status, "capture_only")

    def test_failed_extraction_is_not_counted_as_read_and_partial_success_is_retained(self) -> None:
        good = self._source("https://a.example/source", "Fact A.")
        bad = self._failed_source("https://b.example/source")
        bundle = ResearchBundle(goal="research", resolved_subject="subject", search_queries=["subject"], sources=[good, bad])
        self.assertEqual([item.source_id for item in independent_read_sources(bundle)], [good.source_id])
        self.assertIn("fewer than two independent extracted sources", research_completion_errors(bundle))
        self.assertEqual(bad.extraction_status, "failed")
        self.assertEqual(bad.error, "timeout")

    def test_two_failed_extractions_do_not_block_three_successful_sources_from_remaining_usable(self) -> None:
        observations = [
            self._failed_source("https://failed-a.example/source"),
            self._source("https://good-a.example/source", "Fact A."),
            self._failed_source("https://failed-b.example/source"),
            self._source("https://good-b.example/source", "Fact B."),
            self._source("https://good-c.example/source", "Fact C."),
        ]
        bounded = dedupe_source_observations(observations)
        self.assertEqual(len(bounded), 5)
        self.assertEqual(len(independent_read_sources(ResearchBundle(goal="research", resolved_subject="subject", search_queries=["subject"], sources=bounded))), 3)
        self.assertEqual(len([item for item in bounded if item.extraction_status == "failed"]), 2)

    def test_unsupported_numeric_claim_is_not_promoted_even_with_unrelated_valid_quote(self) -> None:
        source = self._source("https://a.example/price", "Alpha price is $99 today.")
        bundle = ResearchBundle(goal="price", resolved_subject="Alpha", search_queries=["Alpha price"], sources=[source])
        raw = {
            "research_synthesis": {
                "claims": [
                    {"text": "Alpha costs $119 today.", "supports": [{"source_id": source.source_id, "quote": "Alpha price is $99 today."}]},
                    {"text": "Alpha costs $99 today.", "supports": [{"source_id": source.source_id, "quote": "Alpha price is $99 today."}]},
                ],
                "conflicts": [],
                "recommendation": None,
                "unknowns": [],
                "follow_up_queries": [],
            }
        }
        apply_verified_synthesis(bundle, raw)
        self.assertEqual([claim.text for claim in bundle.claims], ["Alpha costs $99 today."])
        self.assertEqual(bundle.rejected_claim_count, 1)

    def test_conflict_requires_distinct_sources_and_exact_observed_quotes(self) -> None:
        a = self._source("https://a.example/price", "Alpha price is $99 today.")
        b = self._source("https://b.example/price", "Alpha price is $119 today.")
        bundle = ResearchBundle(goal="price", resolved_subject="Alpha", search_queries=["Alpha price"], sources=[a, b])
        raw = {
            "research_synthesis": {
                "claims": [{"text": "Two sources disagree on Alpha price.", "supports": [{"source_id": a.source_id, "quote": "Alpha price is $99 today."}, {"source_id": b.source_id, "quote": "Alpha price is $119 today."}]}],
                "conflicts": [{"field": "Alpha price", "claims": [{"value": "$99", "source_id": a.source_id, "quote": "Alpha price is $99 today."}, {"value": "$119", "source_id": b.source_id, "quote": "Alpha price is $119 today."}], "status": "unresolved"}],
                "recommendation": None,
                "unknowns": [],
                "follow_up_queries": [],
            }
        }
        apply_verified_synthesis(bundle, raw)
        self.assertEqual(len(bundle.conflicts), 1)
        self.assertEqual({claim.source_id for claim in bundle.conflicts[0].claims}, {a.source_id, b.source_id})

    def test_evidence_pack_is_bounded_and_contains_only_source_documents_not_provider_answer(self) -> None:
        sources = [
            self._source(f"https://source-{index}.example/page", "x" * (MAX_SOURCE_TEXT_CHARS + 500), provider="fixture")
            for index in range(MAX_SELECTED_SOURCES + 3)
        ]
        bundle = ResearchBundle(goal="research", resolved_subject="subject", search_queries=["subject"], sources=dedupe_source_observations(sources))
        pack = evidence_pack(bundle)
        self.assertLessEqual(len(pack["sources"]), MAX_SELECTED_SOURCES)
        self.assertLessEqual(sum(len(item["evidence_text"]) for item in pack["sources"]), MAX_TOTAL_EVIDENCE_CHARS)
        self.assertTrue(all(len(item["evidence_text"]) <= MAX_SOURCE_TEXT_CHARS for item in pack["sources"]))
        self.assertTrue(all("answer" not in item for item in pack["sources"]))

    def test_canonical_source_url_keeps_meaningful_query_but_drops_fragment_and_trackers(self) -> None:
        self.assertEqual(
            canonical_source_url("HTTPS://Example.COM:443/product/?b=2&utm_medium=x&a=1#details"),
            "https://example.com/product?a=1&b=2",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
