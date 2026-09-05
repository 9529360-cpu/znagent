from __future__ import annotations

import json
import os

from zn_agent.core.cognitive_resource import OpenAICompatibleCognitiveResource
from zn_agent.core.models import ModelRoute


route = ModelRoute(
    route_id="local-real-qwen",
    provider="custom",
    model=os.environ["ZN_LOCAL_MODEL_ID"],
    capabilities={
        "general": 1.0,
        "reasoning": 1.0,
        "coding": 1.0,
        "language_understanding": 1.0,
    },
    metadata={
        "base_url": "http://127.0.0.1:18080/v1",
        "timeout": 180,
        "max_tokens": 512,
        "temperature": 0.0,
    },
)
resource = OpenAICompatibleCognitiveResource(route)
result = resource.invoke(
    question=(
        "Before any execution, define the Root acceptance contract. Return ONLY JSON shaped exactly as "
        '{"zn_root_acceptance":{"criteria":["observable criterion","observable criterion"]}}. '
        "Do not use Markdown fences or prose before/after the JSON. "
        "Root objective: Build a tiny local reading-list product that is runnable and keeps saved items after restart."
    ),
    context="ZN owns execution and final verification; you only define observable success criteria.",
)
print("ZN_LOCAL_MODEL_RAW=" + repr(result.text[:3000]), flush=True)
raw = json.loads(result.text)
criteria = raw.get("zn_root_acceptance", {}).get("criteria")
assert isinstance(criteria, list) and len(criteria) >= 2, result.text
print(
    "ZN_REAL_LOCAL_COGNITION_OK provider=%s model=%s criteria_count=%s"
    % (result.provider, result.model, len(criteria))
)
