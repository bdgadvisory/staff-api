from __future__ import annotations

import uuid

from staff.llm_router.types import OutputClass, TaskContext
from staff.workflows.executor import ExecutorResult, WorkflowExecutor
from staff.workflows.loader import load_workflow
from typing import Literal

from staff.workflows.types import WorkflowState

Audience = Literal["parents", "parent", "child", "family", "public", "internal", "approval_chain"]


def run_linkedin(executor: WorkflowExecutor, ctx: TaskContext, text: str, workflow_path: str, *, audience: Audience | None = None) -> ExecutorResult:
    wf = load_workflow(workflow_path)
    # Default: LinkedIn is public-facing content (even if an approval gate exists).
    aud: Audience = audience or "public"

    state = WorkflowState(
        workflow_id=str(uuid.uuid4()),
        workflow_type=wf.name,
        department=ctx.department,
        task_type=ctx.task_type,
        output_class=OutputClass.C,
        input_payload={"text": text, "subject_ids": [], "audience": aud},
        audit_context={"workflow": wf.name, "audience": aud, "workflow_path": workflow_path},
    )
    return executor.run(ctx, wf, state)


def run_nestor(
    executor: WorkflowExecutor,
    ctx: TaskContext,
    text: str,
    subject_ids: list[str],
    workflow_path: str,
    *,
    audience: Audience | None = None,
) -> ExecutorResult:
    wf = load_workflow(workflow_path)
    # Conservative default: family-sensitive Nestor workflows default to parents.
    # If caller truly intends non-parent audience, they must set it explicitly.
    aud: Audience = audience or "parents"

    state = WorkflowState(
        workflow_id=str(uuid.uuid4()),
        workflow_type=wf.name,
        department=ctx.department,
        task_type=ctx.task_type,
        output_class=OutputClass.C,
        input_payload={"text": text, "subject_ids": subject_ids, "audience": aud},
        audit_context={"workflow": wf.name, "audience": aud, "workflow_path": workflow_path},
    )
    return executor.run(ctx, wf, state)
