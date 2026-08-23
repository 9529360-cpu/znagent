from __future__ import annotations

"""Resident-owned formation of one bounded repository test identity.

The existing procedural resident already knows how to persist, execute and
recheck an explicitly typed ``python_unittest`` verifier. This layer adds only
identity formation for ZN's own top-level resident-kernel modules. Authority is
formed from current repository evidence, never from task prose, model output,
procedural memory, or a caller-supplied command.
"""

import hashlib
import os
from pathlib import Path
from typing import Any

from .procedural_resident import ProcedurallyInfluencedResidentRuntime
from .repo_test_semantics import (
    canonical_kernel_unittest_identity,
    ci_source_runs_kernel_unittest_suite,
    test_source_directly_imports_target,
    test_source_has_discoverable_unittest_case,
)


class RepositoryVerifyingResidentRuntime(ProcedurallyInfluencedResidentRuntime):
    """Procedural resident with bounded current-repository test formation."""

    _RESIDENT_TEST_IDENTITY_SOURCE = "resident_repo_evidence"
    _RESIDENT_TEST_SOURCE_MAX_CHARS = 100_000

    def _targeted_test_requested(self, event) -> bool:
        """Treat a durable resident-formed identity as required after formation.

        Before an identity exists, automatic test formation is optional: lack of
        sufficient evidence leaves the existing tracked repo-delta verifier in
        place. Once the identity is persisted before movement, however, restart
        or later verification must not silently drop it.
        """

        if super()._targeted_test_requested(event):
            return True
        state = self.store.get_working_state()
        if str(state.current_event_id or "") != str(event.event_id):
            return False
        baseline = state.data.get(self._REPO_TEXT_BASELINE_KEY)
        targeted = (
            baseline.get("targeted_test")
            if isinstance(baseline, dict)
            else None
        )
        return bool(
            isinstance(targeted, dict)
            and targeted.get("identity_source") == self._RESIDENT_TEST_IDENTITY_SOURCE
        )

    def _repo_targeted_test_spec(
        self,
        event,
        scope: dict[str, str],
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Prefer explicit typed authority; otherwise prove one ZN-owned identity."""

        if super()._targeted_test_requested(event):
            return super()._repo_targeted_test_spec(event, scope)

        identity = canonical_kernel_unittest_identity(scope.get("relative_path"))
        if identity is None:
            return None, None

        test_file = self._resolved_repo_file(scope, identity["test_relative_path"])
        ci_file = self._resolved_repo_file(scope, identity["ci_relative_path"])
        if test_file is None or ci_file is None:
            return None, None

        test_text, _, test_problems = self._observe_resident_identity_file(
            event,
            scope,
            identity["test_relative_path"],
            label="candidate test",
        )
        ci_text, _, ci_problems = self._observe_resident_identity_file(
            event,
            scope,
            identity["ci_relative_path"],
            label="kernel CI contract",
        )
        if test_problems or ci_problems:
            return None, None
        if not test_source_directly_imports_target(
            test_text,
            identity["target_module"],
        ):
            return None, None
        if not test_source_has_discoverable_unittest_case(test_text):
            return None, None
        if not ci_source_runs_kernel_unittest_suite(ci_text):
            return None, None

        return {
            "kind": self._TARGETED_TEST_KIND,
            "root": scope["root"],
            "head": scope["head"],
            "relative_path": identity["test_relative_path"],
            "for_relative_path": identity["target_relative_path"],
            "timeout": self._TARGETED_TEST_DEFAULT_TIMEOUT,
            "identity_source": self._RESIDENT_TEST_IDENTITY_SOURCE,
            "target_module": identity["target_module"],
            "ci_relative_path": identity["ci_relative_path"],
        }, None

    @staticmethod
    def _resolved_repo_file(
        scope: dict[str, str],
        relative_path: str,
    ) -> Path | None:
        try:
            root = Path(scope["root"]).expanduser().resolve(strict=True)
            lexical = Path(os.path.abspath(str(root / Path(relative_path))))
            resolved = lexical.resolve(strict=True)
            if resolved != lexical or not resolved.is_file():
                return None
            resolved.relative_to(root)
            return resolved
        except (KeyError, OSError, RuntimeError, ValueError):
            return None

    def _observe_resident_identity_file(
        self,
        event,
        scope: dict[str, str],
        relative_path: str,
        *,
        label: str,
    ) -> tuple[str, dict[str, Any], list[str]]:
        """Observe one clean tracked identity file and its exact current text."""

        problems: list[str] = []
        resolved = self._resolved_repo_file(scope, relative_path)
        if resolved is None:
            return "", {}, [f"{label} does not resolve to one regular repository file"]

        git_observation = self.body.act(
            "git_diff",
            event_id=event.event_id,
            path=scope["root"],
            relative_path=relative_path,
        )
        data = (
            git_observation.data
            if isinstance(git_observation.data, dict)
            else {}
        )
        worktree = data.get("worktree") if isinstance(data.get("worktree"), dict) else {}
        staged = data.get("staged") if isinstance(data.get("staged"), dict) else {}
        if not git_observation.success:
            problems.append(
                git_observation.error or f"{label} Git evidence could not be observed"
            )
        else:
            if str(data.get("root") or "") != scope["root"]:
                problems.append(f"{label} repository root changed")
            if str(data.get("head") or "") != scope["head"]:
                problems.append(f"{label} repository HEAD changed")
            if str(data.get("scope_relative_path") or "") != relative_path:
                problems.append(f"{label} resolved a different repository path")
            if data.get("scope_tracked") is not True:
                problems.append(f"{label} is not tracked")
            if bool(data.get("truncated")):
                problems.append(f"{label} Git evidence is truncated")
            if list(worktree.get("paths") or ()):
                problems.append(f"{label} has unstaged changes")
            if list(staged.get("paths") or ()):
                problems.append(f"{label} has staged changes")
            if list(data.get("untracked_paths") or ()):
                problems.append(f"{label} became untracked")

        text_observation = self.body.act(
            "read_text",
            event_id=event.event_id,
            path=str(resolved),
            max_chars=self._RESIDENT_TEST_SOURCE_MAX_CHARS,
        )
        if not text_observation.success:
            problems.append(
                text_observation.error or f"{label} source could not be observed"
            )
            text = ""
        else:
            text = text_observation.output
            if bool(text_observation.data.get("truncated")):
                problems.append(f"{label} source is too large for bounded identity proof")

        snapshot = {
            "relative_path": relative_path,
            "state_sha256": str(data.get("state_sha256") or ""),
            "worktree_patch_sha256": str(worktree.get("patch_sha256") or ""),
            "staged_patch_sha256": str(staged.get("patch_sha256") or ""),
            "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "git_action_id": git_observation.action_id,
            "read_action_id": text_observation.action_id,
        }
        if git_observation.success and not all(
            snapshot[key]
            for key in (
                "state_sha256",
                "worktree_patch_sha256",
                "staged_patch_sha256",
            )
        ):
            problems.append(f"{label} evidence is missing deterministic fingerprints")
        return text, snapshot, problems

    def _observe_targeted_test_snapshot(
        self,
        event,
        spec: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        snapshot, problems = super()._observe_targeted_test_snapshot(event, spec)
        if spec.get("identity_source") != self._RESIDENT_TEST_IDENTITY_SOURCE:
            return snapshot, problems

        scope = {
            "root": str(spec.get("root") or ""),
            "head": str(spec.get("head") or ""),
        }
        test_text, test_evidence, test_problems = self._observe_resident_identity_file(
            event,
            scope,
            str(spec.get("relative_path") or ""),
            label="resident-formed targeted test",
        )
        ci_text, ci_evidence, ci_problems = self._observe_resident_identity_file(
            event,
            scope,
            str(spec.get("ci_relative_path") or ""),
            label="resident-formed kernel CI contract",
        )
        problems.extend(test_problems)
        problems.extend(ci_problems)

        target_module = str(spec.get("target_module") or "")
        if not test_problems:
            if not test_source_directly_imports_target(test_text, target_module):
                problems.append(
                    "resident-formed targeted test no longer directly imports the mutation target"
                )
            elif not test_source_has_discoverable_unittest_case(test_text):
                problems.append(
                    "resident-formed targeted test no longer exposes a discoverable unittest case"
                )
        if not ci_problems and not ci_source_runs_kernel_unittest_suite(ci_text):
            problems.append(
                "resident-formed kernel CI contract no longer runs the bounded unittest suite"
            )

        snapshot.update(
            {
                "identity_source": self._RESIDENT_TEST_IDENTITY_SOURCE,
                "target_module": target_module,
                "ci_relative_path": str(spec.get("ci_relative_path") or ""),
                "test_source_sha256": test_evidence.get("source_sha256", ""),
                "ci_source_sha256": ci_evidence.get("source_sha256", ""),
                "ci_state_sha256": ci_evidence.get("state_sha256", ""),
                "ci_worktree_patch_sha256": ci_evidence.get(
                    "worktree_patch_sha256", ""
                ),
                "ci_staged_patch_sha256": ci_evidence.get(
                    "staged_patch_sha256", ""
                ),
            }
        )
        return snapshot, problems

    @staticmethod
    def _targeted_test_snapshot_matches(
        expected: dict[str, Any],
        observed: dict[str, Any],
    ) -> bool:
        if not ProcedurallyInfluencedResidentRuntime._targeted_test_snapshot_matches(
            expected,
            observed,
        ):
            return False
        source = expected.get("identity_source")
        if source != RepositoryVerifyingResidentRuntime._RESIDENT_TEST_IDENTITY_SOURCE:
            return source == observed.get("identity_source")
        keys = (
            "identity_source",
            "target_module",
            "ci_relative_path",
            "test_source_sha256",
            "ci_source_sha256",
            "ci_state_sha256",
            "ci_worktree_patch_sha256",
            "ci_staged_patch_sha256",
        )
        return all(expected.get(key) == observed.get(key) for key in keys)
