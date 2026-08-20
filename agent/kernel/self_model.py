from __future__ import annotations

import re

from .models import Assessment, CapabilityEstimate
from .store import KernelStore


class SelfModel:
    """Compact evidence-backed model of what ZN knows and can do itself.

    Three kinds of evidence deliberately remain separate:

    - ``route:*`` describes what an external cognitive route is good at.
    - ``knowledge:*`` describes domains ZN has learned or become familiar with.
    - ``self:*`` describes work ZN has actually completed with native/local ability.

    A model solving a problem therefore never makes ZN claim that it can now
    perform that work independently. External cognition can deepen knowledge;
    independent ability grows only from native evidence.
    """

    SELF_PREFIX = "self:"
    KNOWLEDGE_PREFIX = "knowledge:"
    ROUTE_PREFIX = "route:"

    # This is intentionally a small coarse ontology, not a skill catalog. It
    # gives ZN stable areas in which many experiences can be consolidated.
    _DOMAIN_ALIASES = {
        "code": "it/programming",
        "coding": "it/programming",
        "programming": "it/programming",
        "software": "it/programming",
        "debugging": "it/programming",
        "python": "it/programming/python",
        "javascript": "it/programming/javascript",
        "typescript": "it/programming/typescript",
        "database": "it/data",
        "sql": "it/data",
        "data": "it/data",
        "linux": "it/systems",
        "system": "it/systems",
        "systems": "it/systems",
        "shell": "it/systems",
        "network": "it/networking",
        "networking": "it/networking",
        "http": "it/networking",
        "dns": "it/networking",
        "security": "it/security",
        "cybersecurity": "it/security",
        "pentest": "it/security",
        "penetration": "it/security",
        "vulnerability": "it/security",
        "research": "research",
        "analysis": "research/analysis",
        "writing": "communication/writing",
        "communication": "communication",
        "planning": "planning",
        "operations": "operations",
        "general": "general",
    }

    _TASK_HINTS = (
        (("python",), "it/programming/python"),
        (("typescript",), "it/programming/typescript"),
        (("javascript", "node.js", "nodejs"), "it/programming/javascript"),
        (("code", "coding", "program", "debug", "bug", "compile"), "it/programming"),
        (("sql", "database", "sqlite", "postgres", "mysql"), "it/data"),
        (("linux", "shell", "bash", "process", "daemon"), "it/systems"),
        (("network", "http", "dns", "tcp", "udp"), "it/networking"),
        (("security", "pentest", "penetration", "vulnerability", "exploit"), "it/security"),
        (("research", "paper", "literature", "study"), "research"),
        (("write", "writing", "document", "draft"), "communication/writing"),
        (("plan", "planning", "schedule"), "planning"),
    )

    def __init__(self, store: KernelStore):
        self.store = store

    @classmethod
    def route_capability_key(cls, route_id: str, capability: str) -> str:
        return f"{cls.ROUTE_PREFIX}{route_id}:{cls._normalize_path(capability)}"

    @classmethod
    def agent_capability_key(cls, capability: str) -> str:
        return f"{cls.SELF_PREFIX}{cls._normalize_path(capability)}"

    @classmethod
    def knowledge_key(cls, capability: str) -> str:
        return f"{cls.KNOWLEDGE_PREFIX}{cls._normalize_path(capability)}"

    @staticmethod
    def _normalize_path(value: str) -> str:
        text = str(value or "general").strip().lower().replace(":", "/")
        text = re.sub(r"[^a-z0-9_+./-]+", "-", text)
        text = re.sub(r"/+", "/", text).strip("/-")
        return text or "general"

    @classmethod
    def _expand_parents(cls, path: str) -> tuple[str, ...]:
        normalized = cls._normalize_path(path)
        if normalized == "general":
            return ("general",)
        parts = [part for part in normalized.split("/") if part]
        return tuple("/".join(parts[: index]) for index in range(1, len(parts) + 1))

    @classmethod
    def _map_label(cls, label: str) -> str:
        normalized = cls._normalize_path(label)
        if "/" in normalized:
            return normalized
        return cls._DOMAIN_ALIASES.get(normalized, normalized)

    @classmethod
    def infer_domains(
        cls,
        task: str,
        capabilities: tuple[str, ...] | list[str] | None = None,
    ) -> tuple[str, ...]:
        """Infer a small reusable domain set without calling any model.

        The result is intentionally hierarchical. For example Python and
        penetration-testing work both include the parent ``it`` rather than
        becoming unrelated one-off skills.
        """
        ordered: list[str] = []

        def add(path: str) -> None:
            for parent in cls._expand_parents(path):
                if parent not in ordered:
                    ordered.append(parent)

        explicit = tuple(
            str(item).strip()
            for item in (capabilities or ())
            if str(item).strip()
        )
        meaningful_explicit = [item for item in explicit if cls._normalize_path(item) != "general"]
        for item in meaningful_explicit:
            add(cls._map_label(item))

        text = f" {str(task or '').lower()} "
        for needles, domain in cls._TASK_HINTS:
            if any(needle in text for needle in needles):
                add(domain)

        if not ordered:
            add("general")
        return tuple(ordered)

    def get(self, capability: str, default: float = 0.0) -> CapabilityEstimate:
        """Return ZN's independent ability estimate for a domain."""
        domain = self._map_label(capability)
        stored = self.store.get_capability(self.agent_capability_key(domain))
        return self._public_estimate(stored, domain, default)

    def knowledge(self, capability: str, default: float = 0.0) -> CapabilityEstimate:
        domain = self._map_label(capability)
        stored = self.store.get_capability(self.knowledge_key(domain))
        return self._public_estimate(stored, domain, default)

    @staticmethod
    def _public_estimate(
        stored: CapabilityEstimate | None,
        name: str,
        default: float,
    ) -> CapabilityEstimate:
        if stored is None:
            return CapabilityEstimate(name=name, score=max(0.0, min(1.0, default)))
        return CapabilityEstimate(
            name=name,
            score=stored.score,
            evidence_count=stored.evidence_count,
            confidence=stored.confidence,
            updated_at=stored.updated_at,
        )

    def route_score(self, route_id: str, capability: str, prior: float) -> float:
        domain = self._map_label(capability)
        estimate = self.store.get_capability(
            self.route_capability_key(route_id, domain)
        )
        if estimate is None or estimate.evidence_count == 0:
            return max(0.0, min(1.0, prior))
        learned_weight = estimate.confidence
        return (estimate.score * learned_weight) + (prior * (1.0 - learned_weight))

    def learn_external_route(
        self,
        route_id: str,
        task: str,
        capabilities: tuple[str, ...],
        assessment: Assessment,
    ) -> None:
        """Learn which external brain is useful without crediting ZN itself."""
        sample = max(0.0, min(1.0, assessment.quality))
        if not assessment.success:
            sample = min(sample, 0.35)
        for domain in self.infer_domains(task, capabilities):
            self._update_key(self.route_capability_key(route_id, domain), sample)

    # Backward-compatible name for callers outside the new resident path.
    def learn(
        self,
        route_id: str,
        capabilities: tuple[str, ...],
        assessment: Assessment,
    ) -> None:
        self.learn_external_route(route_id, "", capabilities, assessment)

    def integrate_external_learning(
        self,
        task: str,
        capabilities: tuple[str, ...],
        *,
        quality: float,
        confidence: float = 1.0,
    ) -> tuple[str, ...]:
        """Fold a solved impasse into compact domain knowledge.

        This records familiarity/understanding only. It deliberately does not
        update ``self:*`` independent-ability estimates and never creates a
        runnable capability.
        """
        domains = self.infer_domains(task, capabilities)
        sample = max(0.0, min(1.0, float(quality))) * max(
            0.0, min(1.0, float(confidence))
        )
        for domain in domains:
            self._update_key(self.knowledge_key(domain), sample)
        return domains

    def observe_knowledge_use(
        self,
        task: str,
        capabilities: tuple[str, ...] = (),
        *,
        quality: float = 1.0,
    ) -> tuple[str, ...]:
        domains = self.infer_domains(task, capabilities)
        sample = max(0.0, min(1.0, float(quality)))
        for domain in domains:
            self._update_key(self.knowledge_key(domain), sample)
        return domains

    def observe_native_outcome(
        self,
        task: str,
        capabilities: tuple[str, ...] = (),
        *,
        success: bool,
        quality: float = 1.0,
    ) -> tuple[str, ...]:
        """Update what ZN can independently do from native/local evidence."""
        domains = self.infer_domains(task, capabilities)
        sample = max(0.0, min(1.0, float(quality))) if success else 0.0
        for domain in domains:
            self._update_key(self.agent_capability_key(domain), sample)
            if success:
                self._update_key(self.knowledge_key(domain), sample)
        return domains

    def _update_key(self, key: str, sample: float) -> CapabilityEstimate:
        current = self.store.get_capability(key) or CapabilityEstimate(
            name=key,
            score=0.0,
        )
        old_n = current.evidence_count
        current.score = ((current.score * old_n) + sample) / (old_n + 1)
        current.evidence_count = old_n + 1
        current.confidence = min(
            0.99,
            current.evidence_count / (current.evidence_count + 3.0),
        )
        self.store.save_capability(current)
        return current

    def weakest(self, limit: int = 5) -> list[CapabilityEstimate]:
        estimates: list[CapabilityEstimate] = []
        for stored in self.store.list_capabilities():
            if not stored.name.startswith(self.SELF_PREFIX):
                continue
            domain = stored.name[len(self.SELF_PREFIX):]
            estimates.append(self._public_estimate(stored, domain, 0.0))
        estimates.sort(key=lambda item: (item.score, -item.evidence_count, item.name))
        return estimates[: max(1, int(limit))]

    def profile(self) -> dict[str, list[CapabilityEstimate]]:
        """Return compact domain-level knowledge and independent ability."""
        knowledge: list[CapabilityEstimate] = []
        ability: list[CapabilityEstimate] = []
        for stored in self.store.list_capabilities():
            if stored.name.startswith(self.KNOWLEDGE_PREFIX):
                domain = stored.name[len(self.KNOWLEDGE_PREFIX):]
                knowledge.append(self._public_estimate(stored, domain, 0.0))
            elif stored.name.startswith(self.SELF_PREFIX):
                domain = stored.name[len(self.SELF_PREFIX):]
                ability.append(self._public_estimate(stored, domain, 0.0))
        knowledge.sort(key=lambda item: item.name)
        ability.sort(key=lambda item: item.name)
        return {"knowledge": knowledge, "ability": ability}
