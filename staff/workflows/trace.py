from __future__ import annotations

from typing import Any

from staff.workflows.types import WorkflowState


def build_trace(state: WorkflowState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, art in enumerate(state.step_artifacts):
        rows.append(
            {
                "workflow_id": state.workflow_id,
                "step_index": idx,
                "step_id": art.step_id,
                "step_type": art.step_type,
                "status": art.status,
                "next_action": art.next_action,
                "approval_status": state.approval_status,
                "review_status": state.review_status,
            }
        )
    return rows


def format_trace(state: WorkflowState) -> str:
    lines = []
    for r in build_trace(state):
        lines.append(
            f"{r['workflow_id']} | #{r['step_index']:02d} | {r['step_id']} | {r['step_type']} | {r['status']}"
            f" | next={r['next_action']} | approval={r['approval_status']} | review={r['review_status']}"
        )
    return "\n".join(lines)
