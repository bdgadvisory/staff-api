from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from staff.llm_router.types import RetrievalBundle, TaskContext


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    actor: dict[str, Any]
    scope: str
    privacy_class: str
    department: str
    task_type: str
    max_graph_edges: int = 20
    max_semantic_chunks: int = 6
    max_episodic_events: int = 12


class RetrievalClient:
    """Retrieval contract boundary.

    The LLM layer must consume memory via this contract (service/API), not by ad hoc file reads.
    This module is where privacy/trust filtering is enforced *before* prompt assembly.
    """

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url

    def retrieve(self, ctx: TaskContext, req: RetrievalRequest) -> RetrievalBundle:
        # Scaffold: in production call Memory Service: GET/POST /memory/retrieve
        # and return the structured bundle.
        return RetrievalBundle(
            graph_facts=[],
            semantic_chunks=[],
            episodic_events=[],
            constraints=[],
            citations=[],
        )
