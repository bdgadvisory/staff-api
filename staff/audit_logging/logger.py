from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from staff.llm_router.types import ConfidenceReport, ModelSelection, RetrievalBundle, TaskContext


@dataclass(frozen=True)
class AuditRecord:
    timestamp: float
    workflow_id: str | None
    step_id: str | None
    step_type: str | None
    department: str
    task_type: str
    selected_capabilities: list[str]
    selected_provider: str
    selected_model: str
    latency_ms: int | None
    cost_estimate: float | None
    review_status: str
    escalation_chain: list[str]
    confidence: ConfidenceReport
    output_class: str
    human_facing: bool
    retrieval_summary: dict[str, Any]
    source_object_ids: list[str]


class AuditLogger:
    """Audit log module.

    MVP: JSONL to stdout/file. In production: Postgres table (episodic) + object store attachments.
    """

    def __init__(self, sink_path: str | None = None):
        self.sink_path = sink_path

    def log(
        self,
        ctx: TaskContext,
        selection: ModelSelection,
        confidence: ConfidenceReport,
        review_status: str,
        escalation_chain: list[str],
        retrieval: RetrievalBundle,
        source_object_ids: list[str],
        *,
        workflow_id: str | None = None,
        step_id: str | None = None,
        step_type: str | None = None,
        latency_ms: int | None = None,
        cost_estimate: float | None = None,
    ) -> None:
        rec = AuditRecord(
            timestamp=time.time(),
            workflow_id=workflow_id,
            step_id=step_id,
            step_type=step_type,
            department=ctx.department,
            task_type=ctx.task_type,
            selected_capabilities=[selection.capability],
            selected_provider=selection.provider,
            selected_model=selection.model,
            latency_ms=latency_ms,
            cost_estimate=cost_estimate,
            review_status=review_status,
            escalation_chain=escalation_chain,
            confidence=confidence,
            output_class=confidence.selected_output_class.value,
            human_facing=ctx.human_facing,
            retrieval_summary={
                "graph_facts": len(retrieval.graph_facts),
                "semantic_chunks": len(retrieval.semantic_chunks),
                "episodic_events": len(retrieval.episodic_events),
                "constraints": len(retrieval.constraints),
            },
            source_object_ids=source_object_ids,
        )

        line = json.dumps(asdict(rec), default=str)
        if self.sink_path:
            with open(self.sink_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            print(line)
