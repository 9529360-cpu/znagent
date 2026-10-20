from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from zn_agent.core import KernelStore
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.approval_cards import APPROVAL_KINDS, validate_approval_kind
from zn_agent.core.body import NativeBody
from zn_agent.core.openapi_rest_adapter import RestHttpResponse
from zn_agent.core.rss_feed_connector import (
    ADD_ACTION_ID,
    APPROVAL_KIND_FEED_SUBSCRIPTION,
    DIGEST_ACTION_ID,
    FETCH_ACTION_ID,
    LIST_ACTION_ID,
    REMOVE_ACTION_ID,
    RssFeedError,
    RssSubscriptionStore,
    add_subscription,
    approved_rss_write_tools,
    attach_rss_tools,
    build_feed_digest,
    fetch_feed,
    list_subscriptions,
    parse_feed_document,
    remove_subscription,
    subscription_postcondition_probes,
)
from zn_agent.core.skill_evals import eval_skills_root

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"

BLOG_URL = "https://blog.example.com/feed.xml"
NEWS_URL = "https://news.example.com/atom.xml"
BROKEN_URL = "https://broken.example.com/feed.xml"


def _rfc822(moment: datetime) -> str:
    return format_datetime(moment.astimezone(timezone.utc))


def _rss_document(items: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        "<title>Example Blog</title>"
        "<link>https://blog.example.com/</link>"
        "<description>Notes from the example blog</description>"
        f"{items}</channel></rss>"
    ).encode("utf-8")


def _blog_feed() -> bytes:
    now = datetime.now(timezone.utc)
    items = "".join(
        [
            "<item><title>Fresh AI post</title>"
            "<link>https://blog.example.com/fresh</link>"
            "<description>&lt;p&gt;All about &lt;b&gt;AI&lt;/b&gt; agents&lt;/p&gt;</description>"
            f"<pubDate>{_rfc822(now - timedelta(hours=1))}</pubDate>"
            "<guid>post-fresh</guid></item>",
            "<item><title>Old cooking post</title>"
            "<link>https://blog.example.com/old</link>"
            "<description>A stew recipe</description>"
            f"<pubDate>{_rfc822(now - timedelta(days=10))}</pubDate>"
            "<guid>post-old</guid></item>",
            "<item><title>Undated note</title>"
            "<link>https://blog.example.com/undated</link>"
            "<description>No date on this one</description>"
            "<pubDate>not a real date</pubDate>"
            "<guid>post-undated</guid></item>",
            # Bad entry: neither title nor link -> skipped and counted.
            "<item><description>orphan description only</description></item>",
        ]
    )
    return _rss_document(items)


def _atom_feed() -> bytes:
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(hours=2)).isoformat()
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<title>Example News</title>"
        '<link href="https://news.example.com/"/>'
        "<subtitle>News subtitle</subtitle>"
        "<entry><title>AI regulation update</title>"
        '<link rel="alternate" href="https://news.example.com/ai-law"/>'
        "<summary>Courts and AI, again</summary>"
        f"<published>{fresh}</published>"
        "<id>tag:news,2026:1</id></entry>"
        "<entry><title>Weather front moves in</title>"
        '<link href="https://news.example.com/weather"/>'
        "<summary>Storm clouds gathering</summary>"
        f"<published>{fresh}</published>"
        "<id>tag:news,2026:2</id></entry>"
        "</feed>"
    ).encode("utf-8")


class _FakeFeedServer:
    """Mock feed endpoints: records calls, answers fixed payloads."""

    def __init__(self):
        self.calls = []
        self.status_overrides: dict[str, int] = {}
        self.transport_error: Exception | None = None

    def request(self, method, url, *, params, headers, json_body, timeout_seconds):
        self.calls.append({"method": method, "url": url})
        if self.transport_error is not None:
            raise self.transport_error
        if url in self.status_overrides:
            return RestHttpResponse(self.status_overrides[url], {}, b"error")
        if url == BLOG_URL:
            return RestHttpResponse(200, {}, _blog_feed())
        if url == NEWS_URL:
            return RestHttpResponse(200, {}, _atom_feed())
        return RestHttpResponse(404, {}, b"not found")


class SubscriptionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "subscriptions.json"
        self.store = RssSubscriptionStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_list_get_remove_roundtrip(self):
        self.assertEqual(self.store.list(), [])
        created = self.store.add("Blog", BLOG_URL)
        self.assertEqual(created.name, "blog")
        self.assertEqual(created.url, BLOG_URL)
        self.assertTrue(created.added_at)
        self.store.add("news", NEWS_URL)
        self.assertEqual(
            [item.name for item in self.store.list()], ["blog", "news"]
        )
        self.assertEqual(self.store.get("BLOG").url, BLOG_URL)
        removed = self.store.remove("blog")
        self.assertEqual(removed.url, BLOG_URL)
        self.assertEqual([item.name for item in self.store.list()], ["news"])

    def test_persistence_is_a_fresh_file_read(self):
        self.store.add("blog", BLOG_URL)
        other = RssSubscriptionStore(self.path)
        self.assertEqual([item.name for item in other.list()], ["blog"])

    def test_duplicate_and_unknown_are_explicit(self):
        self.store.add("blog", BLOG_URL)
        with self.assertRaises(RssFeedError) as caught:
            self.store.add("blog", NEWS_URL)
        self.assertIn("already exists", str(caught.exception))
        with self.assertRaises(RssFeedError) as caught:
            self.store.remove("nope")
        self.assertIn("unknown subscription", str(caught.exception))

    def test_invalid_name_and_url_are_explicit(self):
        with self.assertRaises(RssFeedError):
            self.store.add("has spaces", BLOG_URL)
        with self.assertRaises(RssFeedError):
            self.store.add("ok-name", "ftp://example.com/feed")
        with self.assertRaises(RssFeedError):
            self.store.add("ok-name", "not-a-url")

    def test_corrupt_store_is_explicit_not_silently_empty(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(RssFeedError) as caught:
            self.store.list()
        self.assertIn("corrupt", str(caught.exception))


class FeedParsingTests(unittest.TestCase):
    def test_rss2_entries_and_bad_entry_tolerance(self):
        parsed = parse_feed_document(_blog_feed())
        self.assertEqual(parsed.format, "rss2")
        self.assertEqual(parsed.title, "Example Blog")
        self.assertEqual(len(parsed.entries), 3)
        self.assertEqual(parsed.skipped_entries, 1)
        fresh = parsed.entries[0]
        self.assertEqual(fresh.title, "Fresh AI post")
        self.assertEqual(fresh.entry_id, "post-fresh")
        self.assertIsNotNone(fresh.published_at)
        # HTML markup in the description is stripped, text remains.
        self.assertEqual(fresh.summary, "All about AI agents")
        # An unparseable date is kept as None, never guessed.
        self.assertIsNone(parsed.entries[2].published_at)

    def test_atom_entries(self):
        parsed = parse_feed_document(_atom_feed())
        self.assertEqual(parsed.format, "atom")
        self.assertEqual(parsed.title, "Example News")
        self.assertEqual(len(parsed.entries), 2)
        first = parsed.entries[0]
        self.assertEqual(first.title, "AI regulation update")
        self.assertEqual(first.link, "https://news.example.com/ai-law")
        self.assertIsNotNone(first.published_at)

    def test_rss1_rdf_document(self):
        document = (
            '<?xml version="1.0"?>'
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
            'xmlns="http://purl.org/rss/1.0/">'
            "<channel><title>RDF Daily</title>"
            "<link>https://rdf.example.com/</link></channel>"
            "<item><title>RDF item</title>"
            "<link>https://rdf.example.com/1</link>"
            "<description>rdf summary</description></item>"
            "</rdf:RDF>"
        ).encode("utf-8")
        parsed = parse_feed_document(document)
        self.assertEqual(parsed.format, "rss1")
        self.assertEqual(parsed.title, "RDF Daily")
        self.assertEqual(len(parsed.entries), 1)

    def test_non_feed_documents_are_explicit_errors(self):
        with self.assertRaises(RssFeedError):
            parse_feed_document(b"<html><body>nope</body></html>")
        with self.assertRaises(RssFeedError):
            parse_feed_document(b"this is not xml at all")
        with self.assertRaises(RssFeedError):
            parse_feed_document(b"")

    def test_entity_declarations_are_refused(self):
        document = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            '<rss version="2.0"><channel><title>&xxe;</title>'
            "</channel></rss>"
        ).encode("utf-8")
        with self.assertRaises(RssFeedError) as caught:
            parse_feed_document(document)
        self.assertIn("entities", str(caught.exception))


class RssConnectorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(Path(self.tmp.name) / "kernel.db")
        )
        self.store = RssSubscriptionStore(
            Path(self.tmp.name) / "subscriptions.json"
        )
        self.client = _FakeFeedServer()
        self.attachment = attach_rss_tools(
            self.fabric,
            self.body,
            store=self.store,
            http_client=self.client,
        )
        self.runtime = ActionExecutionRuntime(self.fabric, self.body)

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def test_attach_registers_read_only_tools(self):
        for action_id in (LIST_ACTION_ID, FETCH_ACTION_ID, DIGEST_ACTION_ID):
            descriptor = self.fabric.descriptor(action_id)
            self.assertIsNotNone(descriptor, action_id)
            self.assertEqual(descriptor.effect_class, "read_only")
            self.assertIn("rss", descriptor.tags)

    def test_writes_are_disabled_without_host_approval(self):
        self.assertIsNone(self.fabric.descriptor(ADD_ACTION_ID))
        self.assertIsNone(self.fabric.descriptor(REMOVE_ACTION_ID))
        self.assertEqual(
            self.attachment.disabled_write_operations,
            ("add_subscription", "remove_subscription"),
        )

    def test_detach_removes_tools(self):
        self.attachment.detach()
        for action_id in (LIST_ACTION_ID, FETCH_ACTION_ID, DIGEST_ACTION_ID):
            self.assertIsNone(self.fabric.descriptor(action_id))

    def test_list_subscriptions_through_runtime(self):
        self.store.add("blog", BLOG_URL)
        answer = list_subscriptions(self.runtime, event_id="evt-rss-1")
        self.assertEqual(answer["count"], 1)
        self.assertEqual(answer["subscriptions"][0]["name"], "blog")
        self.assertEqual(answer["subscriptions"][0]["url"], BLOG_URL)

    def test_fetch_feed_by_name_through_runtime(self):
        self.store.add("blog", BLOG_URL)
        answer = fetch_feed(
            self.runtime, name="blog", event_id="evt-rss-2"
        )
        self.assertEqual(answer["subscription"], "blog")
        self.assertEqual(answer["source_url"], BLOG_URL)
        self.assertEqual(answer["feed"]["format"], "rss2")
        self.assertEqual(answer["feed"]["skipped_entries"], 1)
        self.assertEqual(len(answer["entries"]), 3)
        self.assertEqual(answer["entries"][0]["title"], "Fresh AI post")

    def test_fetch_feed_by_url_and_unknown_name(self):
        answer = fetch_feed(
            self.runtime, url=NEWS_URL, event_id="evt-rss-3"
        )
        self.assertEqual(answer["feed"]["format"], "atom")
        with self.assertRaises(RssFeedError) as caught:
            fetch_feed(self.runtime, name="ghost", event_id="evt-rss-4")
        self.assertIn("unknown subscription", str(caught.exception))
        with self.assertRaises(RssFeedError):
            fetch_feed(self.runtime, event_id="evt-rss-5")

    def test_fetch_http_and_transport_failures_are_explicit(self):
        self.client.status_overrides[BLOG_URL] = 500
        with self.assertRaises(RssFeedError) as caught:
            fetch_feed(self.runtime, url=BLOG_URL, event_id="evt-rss-6")
        self.assertIn("500", str(caught.exception))
        self.client.status_overrides.clear()
        self.client.transport_error = ConnectionError("network down")
        with self.assertRaises(RssFeedError) as caught:
            fetch_feed(self.runtime, url=BLOG_URL, event_id="evt-rss-7")
        self.assertIn("fetch", str(caught.exception))

    def test_digest_keyword_and_recency_filters(self):
        self.store.add("blog", BLOG_URL)
        self.store.add("news", NEWS_URL)
        digest = build_feed_digest(
            self.runtime, keyword="ai", event_id="evt-rss-8"
        )
        titles = [entry["title"] for entry in digest["entries"]]
        self.assertEqual(
            titles, ["Fresh AI post", "AI regulation update"]
        )
        self.assertEqual(digest["feeds_checked"], 2)
        self.assertEqual(digest["feed_errors"], [])
        self.assertEqual(
            digest["entries"][0]["feed_name"], "blog"
        )
        recent = build_feed_digest(
            self.runtime, since_hours=24, event_id="evt-rss-9"
        )
        recent_titles = [entry["title"] for entry in recent["entries"]]
        self.assertNotIn("Old cooking post", recent_titles)
        self.assertNotIn("Undated note", recent_titles)
        self.assertEqual(recent["undated_entries_excluded"], 1)

    def test_digest_tolerates_one_broken_feed(self):
        self.store.add("blog", BLOG_URL)
        self.store.add("broken", BROKEN_URL)
        digest = build_feed_digest(self.runtime, event_id="evt-rss-10")
        self.assertEqual(digest["feeds_checked"], 2)
        self.assertEqual(len(digest["feed_errors"]), 1)
        self.assertEqual(digest["feed_errors"][0]["name"], "broken")
        self.assertIn("404", digest["feed_errors"][0]["error"])
        self.assertTrue(digest["entries"])


class RssWriteContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(Path(self.tmp.name) / "kernel.db")
        )
        self.store = RssSubscriptionStore(
            Path(self.tmp.name) / "subscriptions.json"
        )
        self.client = _FakeFeedServer()
        self.attachment = attach_rss_tools(
            self.fabric,
            self.body,
            store=self.store,
            http_client=self.client,
            approved_write_tools=approved_rss_write_tools(),
            postcondition_probes=subscription_postcondition_probes(self.store),
        )
        self.runtime = ActionExecutionRuntime(self.fabric, self.body)

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def test_approval_kind_is_registered(self):
        self.assertIn(APPROVAL_KIND_FEED_SUBSCRIPTION, APPROVAL_KINDS)
        self.assertEqual(
            validate_approval_kind(APPROVAL_KIND_FEED_SUBSCRIPTION),
            "feed_subscription",
        )
        for tool in approved_rss_write_tools():
            self.assertEqual(
                tool.approval_kind, APPROVAL_KIND_FEED_SUBSCRIPTION
            )

    def test_add_and_remove_verify_through_postcondition(self):
        self.attachment.register_verifications(self.runtime)
        added = add_subscription(
            self.runtime, "blog", BLOG_URL, event_id="evt-rss-w1"
        )
        self.assertEqual(added["subscription"]["name"], "blog")
        self.assertEqual(self.store.get("blog").url, BLOG_URL)
        outcome = self.runtime.execute(
            ActionRequest(
                REMOVE_ACTION_ID, {"name": "blog"}, event_id="evt-rss-w2"
            )
        )
        self.assertTrue(outcome.success, outcome.error)
        self.assertEqual(outcome.verification.status, "verified")
        self.assertIsNone(self.store.get("blog"))

    def test_write_replay_is_refused_without_redispatch(self):
        self.attachment.register_verifications(self.runtime)
        add_subscription(
            self.runtime, "blog", BLOG_URL, event_id="evt-rss-w3"
        )
        outcome = self.runtime.execute(
            ActionRequest(
                ADD_ACTION_ID,
                {"name": "blog", "url": BLOG_URL},
                event_id="evt-rss-w3",
            )
        )
        self.assertFalse(outcome.success)
        self.assertIn("replay refused", outcome.error)
        # A genuinely new occurrence (new event) still hits the store's
        # own duplicate guard instead of silently overwriting.
        with self.assertRaises(RssFeedError) as caught:
            add_subscription(
                self.runtime, "blog", NEWS_URL, event_id="evt-rss-w4"
            )
        self.assertIn("already exists", str(caught.exception))

    def test_write_without_verifications_wiring_fails_closed(self):
        # Deliberately NOT calling register_verifications.
        with self.assertRaises(RssFeedError) as caught:
            add_subscription(
                self.runtime, "blog", BLOG_URL, event_id="evt-rss-w5"
            )
        self.assertIn(
            "no independent postcondition verifier", str(caught.exception)
        )

    def test_attach_rejects_mismatched_probes(self):
        fabric = ActionFabricRegistry()
        body = NativeBody(
            store=KernelStore(Path(self.tmp.name) / "kernel2.db")
        )
        try:
            with self.assertRaises(ValueError):
                attach_rss_tools(
                    fabric,
                    body,
                    store=self.store,
                    http_client=self.client,
                    approved_write_tools=approved_rss_write_tools(),
                    postcondition_probes={},
                )
        finally:
            body.store.close()


class RssSkillEvalTests(unittest.TestCase):
    def test_repo_rss_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        rss = [
            item for item in report.tier1 if item.skill_name == "rss-reader"
        ]
        self.assertEqual(len(rss), 1, report.to_dict())
        self.assertTrue(rss[0].passed, rss[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


def _padded_feed(padding_bytes: int) -> bytes:
    padding = "<!--" + ("x" * padding_bytes) + "-->"
    return _rss_document(
        padding
        + "<item><title>Padded post</title>"
        "<link>https://blog.example.com/padded</link>"
        "<description>real entry after the padding</description></item>"
    )


class _FeedRequestHandler(BaseHTTPRequestHandler):
    payloads: dict[str, bytes] = {}

    def do_GET(self):
        payload = self.payloads.get(self.path)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):  # silence test server logging
        pass


class DefaultTransportTests(unittest.TestCase):
    """The default (urllib) transport against a real local HTTP server.

    Regression guard for the shared REST transport's 1 MB silent
    truncation: a valid feed between 1 MB and the 5 MB feed bound
    must parse whole, and an oversized feed must fail explicitly.
    """

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer

        _FeedRequestHandler.payloads = {
            "/small.xml": _blog_feed(),
            "/big.xml": _padded_feed(1_500_000),
            "/huge.xml": _padded_feed(5_200_000),
        }
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _FeedRequestHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(Path(self.tmp.name) / "kernel.db")
        )
        self.store = RssSubscriptionStore(
            Path(self.tmp.name) / "subscriptions.json"
        )
        # No http_client: the default urllib feed transport is used.
        self.attachment = attach_rss_tools(
            self.fabric, self.body, store=self.store
        )
        self.runtime = ActionExecutionRuntime(self.fabric, self.body)

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def test_small_feed_over_real_http(self):
        answer = fetch_feed(
            self.runtime, url=f"{self.base}/small.xml", event_id="evt-http-1"
        )
        self.assertEqual(answer["feed"]["format"], "rss2")
        self.assertEqual(len(answer["entries"]), 3)

    def test_feed_above_rest_cap_parses_whole(self):
        answer = fetch_feed(
            self.runtime, url=f"{self.base}/big.xml", event_id="evt-http-2"
        )
        self.assertEqual(len(answer["entries"]), 1)
        self.assertEqual(answer["entries"][0]["title"], "Padded post")

    def test_oversized_feed_fails_explicitly(self):
        with self.assertRaises(RssFeedError) as caught:
            fetch_feed(
                self.runtime, url=f"{self.base}/huge.xml", event_id="evt-http-3"
            )
        self.assertIn("exceeds", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
