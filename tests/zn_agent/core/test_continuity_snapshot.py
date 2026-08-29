from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from zn_agent.core.continuity import (
    ContinuitySnapshotService,
    compare_continuity_snapshots,
)


class _Work:
    def __init__(self):
        self.requested_limit = None

    def list_threads(self, *, limit: int):
        self.requested_limit = limit
        return [
            SimpleNamespace(
                thread_id="work-z",
                title="private task title",
                metadata={"private": "metadata"},
                created_at="2026-01-02T00:00:00+00:00",
            ),
            SimpleNamespace(
                thread_id="work-a",
                title="another private title",
                metadata={},
                created_at="2026-01-01T00:00:00+00:00",
            ),
        ]


class _VerifiedExperiences:
    def recent(self, limit: int):
        return [
            SimpleNamespace(experience_id="vx-z", task="private causal task"),
            SimpleNamespace(experience_id="vx-a", verification={"private": "evidence"}),
        ][:limit]

    def count(self):
        return 2


class _ProviderSettings:
    def snapshot(self):
        return {
            "mode": "default",
            "provider": "openai",
            "model": "gpt-test",
            "base_url": "https://example.invalid/v1",
            "credential": {
                "configured": True,
                "source": "secure_store",
                "environment_name": None,
                "secure_store": {
                    "available": True,
                    "backend": "secret-backend-detail",
                    "error": "secret-store-error-detail",
                },
            },
            "active_routes": [
                {"id": "route-z", "provider": "openai", "model": "gpt-z", "api_key": "route-secret"},
                {"id": "route-a", "provider": "openai", "model": "gpt-a"},
            ],
            "cognition_available": True,
            "configuration_error": "private config error",
            "api_key": "top-level-secret",
        }


def _snapshot(*, work_ids=("work-a",), learning_ids=("vx-a",), provider="openai"):
    return {
        "schema_version": ContinuitySnapshotService.SCHEMA_VERSION,
        "identity": {
            "name": "ZN Agent",
            "version": "0.2.0",
            "created_at": "identity-born",
            "updated_at": "identity-now",
        },
        "living_self": {
            "name": "ZN",
            "version": "0.2.0",
            "born_at": "living-born",
            "wake_count": 2,
            "pulse_count": 3,
            "last_event_id": None,
            "learning_candidate_ids": [],
        },
        "work": {
            "reference_count": len(work_ids),
            "reference_limit": 100,
            "references_may_be_truncated": False,
            "threads": [{"id": item, "created_at": "thread-born"} for item in work_ids],
        },
        "verified_learning": {
            "reference_count": len(learning_ids),
            "total_count": len(learning_ids),
            "reference_limit": 256,
            "references_may_be_truncated": False,
            "experience_ids": list(learning_ids),
        },
        "provider": {
            "mode": "default",
            "provider": provider,
            "model": "model-a",
            "base_url": "",
            "credential": {
                "configured": False,
                "source": "none",
                "environment_name": None,
            },
            "active_routes": [],
            "cognition_available": False,
        },
    }


class ContinuitySnapshotTests(unittest.TestCase):
    def test_snapshot_exports_only_bounded_non_secret_continuity_references(self):
        resident = SimpleNamespace(
            identity=SimpleNamespace(
                name="ZN Agent",
                version="0.2.0",
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-03T00:00:00+00:00",
                purpose="private long description",
            ),
            life=SimpleNamespace(
                snapshot=lambda: SimpleNamespace(
                    name="ZN",
                    version="0.2.0",
                    born_at="2026-01-01T00:00:00+00:00",
                    wake_count=3,
                    pulse_count=9,
                    last_event_id="evt-1",
                    learning_candidates=("learn-z", "learn-a"),
                    attention="private task text",
                    observations=("private observation",),
                )
            ),
            verified_experiences=_VerifiedExperiences(),
        )
        work = _Work()
        snapshot = ContinuitySnapshotService(
            resident,
            work=work,
            provider_settings=_ProviderSettings(),
        ).snapshot()

        self.assertEqual(snapshot["schema_version"], 2)
        self.assertEqual(work.requested_limit, ContinuitySnapshotService.WORK_REFERENCE_LIMIT)
        self.assertEqual(
            [item["id"] for item in snapshot["work"]["threads"]],
            ["work-a", "work-z"],
        )
        self.assertEqual(snapshot["work"]["reference_count"], 2)
        self.assertFalse(snapshot["work"]["references_may_be_truncated"])
        self.assertEqual(
            snapshot["living_self"]["learning_candidate_ids"],
            ["learn-a", "learn-z"],
        )
        self.assertEqual(
            snapshot["verified_learning"]["experience_ids"],
            ["vx-a", "vx-z"],
        )
        self.assertEqual(snapshot["verified_learning"]["total_count"], 2)
        self.assertEqual(
            [item["id"] for item in snapshot["provider"]["active_routes"]],
            ["route-a", "route-z"],
        )

        rendered = json.dumps(snapshot, sort_keys=True)
        for forbidden in (
            "private task title",
            "another private title",
            "metadata",
            "private long description",
            "private task text",
            "private observation",
            "private causal task",
            "evidence",
            "top-level-secret",
            "route-secret",
            "secret-backend-detail",
            "secret-store-error-detail",
            "private config error",
            "api_key",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_full_reference_window_is_marked_potentially_truncated(self):
        threads = [
            SimpleNamespace(thread_id=f"work-{index:03d}", created_at="2026-01-01T00:00:00+00:00")
            for index in range(ContinuitySnapshotService.WORK_REFERENCE_LIMIT)
        ]
        work = SimpleNamespace(list_threads=lambda *, limit: threads[:limit])
        resident = SimpleNamespace(
            identity=SimpleNamespace(
                name="ZN Agent", version="0.2.0", created_at="born", updated_at="now"
            ),
            life=SimpleNamespace(
                snapshot=lambda: SimpleNamespace(
                    name="ZN",
                    version="0.2.0",
                    born_at="born",
                    wake_count=1,
                    pulse_count=1,
                    last_event_id=None,
                    learning_candidates=(),
                )
            ),
        )
        provider = SimpleNamespace(snapshot=lambda: {})
        snapshot = ContinuitySnapshotService(
            resident,
            work=work,
            provider_settings=provider,
        ).snapshot()
        self.assertTrue(snapshot["work"]["references_may_be_truncated"])
        self.assertEqual(snapshot["work"]["reference_count"], 100)
        self.assertEqual(snapshot["verified_learning"]["reference_count"], 0)

    def test_continuity_verdict_accepts_version_change_when_subject_references_survive(self):
        before = _snapshot(work_ids=("work-a",), learning_ids=("vx-a",))
        after = _snapshot(
            work_ids=("work-a", "work-b"),
            learning_ids=("vx-a", "vx-b"),
            provider="anthropic",
        )
        after["identity"]["version"] = "0.3.0"
        after["living_self"]["version"] = "0.3.0"

        verdict = compare_continuity_snapshots(before, after)

        self.assertTrue(verdict["compatible"])
        self.assertEqual(verdict["blockers"], [])
        self.assertEqual(verdict["warnings"][0]["kind"], "provider_reference_changed")

    def test_continuity_verdict_blocks_identity_birth_or_learning_loss(self):
        before = _snapshot(
            work_ids=("work-a", "work-b"),
            learning_ids=("vx-a", "vx-b"),
        )
        after = _snapshot(work_ids=("work-a",), learning_ids=("vx-a",))
        after["living_self"]["born_at"] = "different-subject"

        verdict = compare_continuity_snapshots(before, after)
        kinds = {item["kind"] for item in verdict["blockers"]}

        self.assertFalse(verdict["compatible"])
        self.assertIn("living_self_birth_changed", kinds)
        self.assertIn("work_references_lost", kinds)
        self.assertIn("verified_learning_references_lost", kinds)

    def test_continuity_verdict_fails_closed_when_post_reference_set_is_truncated(self):
        before = _snapshot(learning_ids=("vx-a", "vx-b"))
        after = _snapshot(learning_ids=("vx-a",))
        after["verified_learning"]["references_may_be_truncated"] = True
        after["verified_learning"]["total_count"] = 300

        verdict = compare_continuity_snapshots(before, after)
        kinds = {item["kind"] for item in verdict["blockers"]}

        self.assertFalse(verdict["compatible"])
        self.assertIn("verified_learning_continuity_unproven", kinds)


if __name__ == "__main__":
    unittest.main()
