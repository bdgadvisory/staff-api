from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import os

import httpx

from staff.llm_router.types import OutputClass, RetrievalBundle, TaskContext


@dataclass(frozen=True)
class RetrievalRequest:
    # HTTP contract fields (POST /v1/retrieve)
    agent_id: str
    department: str
    task_type: str
    query: str
    scope: str
    subject_ids: list[str]
    output_class: OutputClass
    max_graph_facts: int = 20
    max_semantic_chunks: int = 6
    max_episodic_events: int = 12
    include_citations: bool = True


class RetrievalClient:
    """HTTP client for staff-memory-service.

    Hard rule: staff-api must NOT read staff-memory directly.
    Retrieval + privacy/trust/staleness/conflict governance happens behind the service boundary.

    Env:
      STAFF_MEMORY_SERVICE_URL (default http://localhost:8088)
      STAFF_MEMORY_SERVICE_MODE=mock|http (default mock)

    """

    def __init__(self, base_url: str | None = None, mode: str | None = None, timeout_s: float = 12.0):
        self.base_url = base_url or os.environ.get("STAFF_MEMORY_SERVICE_URL", "http://localhost:8088")
        self.mode = mode or os.environ.get("STAFF_MEMORY_SERVICE_MODE", "mock")
        self.timeout_s = timeout_s

    def retrieve(self, ctx: TaskContext, req: RetrievalRequest) -> RetrievalBundle:
        if self.mode == "mock":
            return self._mock_bundle(req)

        url = f"{self.base_url.rstrip('/')}/v1/retrieve"
        payload = {
            **asdict(req),
            "output_class": req.output_class.value,
        }

        with httpx.Client(timeout=self.timeout_s) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return RetrievalBundle(
            graph_facts=data.get("graph_facts", []),
            semantic_chunks=data.get("semantic_chunks", []),
            episodic_events=data.get("episodic_events", []),
            constraints=data.get("constraints", []),
            citations=data.get("citations", []),
            retrieval_meta=data.get("retrieval_meta", {}),
        )

    def _mock_bundle(self, req: RetrievalRequest) -> RetrievalBundle:
        # Local testing stub that still respects the *shape* of the HTTP contract.
        return RetrievalBundle(
            graph_facts=[
                {"fact": "mock_permission", "value": "allowed", "source": "mock"},
            ],
            semantic_chunks=[
                {
                    "doc_id": "mock/qmd/policy-001",
                    "type": "policy",
                    "trust_level": "system_verified",
                    "privacy_class": "internal",
                    "review_after": "2099-01-01",
                    "text": "Cheap models may gather. Strong models must speak for Class C outputs.",
                }
            ],
            episodic_events=[],
            constraints=[
                {"constraint": "class_c_requires_review", "applies": req.output_class.value == "C"},
            ],
            citations=[{"object_id": "mock/qmd/policy-001"}],
            retrieval_meta={
                "stale_items_present": False,
                "conflicts_present": False,
                "privacy_filters_applied": [],
                "trust_filters_applied": [],
                "source_object_ids": ["mock/qmd/policy-001"],
            },
        )
