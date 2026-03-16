from __future__ import annotations

import uuid

from staff.llm_router.types import OutputClass, TaskContext
from staff.workflows.executor import ExecutorResult, WorkflowExecutor
from staff.workflows.loader import load_workflow
from staff.workflows.types import WorkflowState


def run_linkedin(executor: WorkflowExecutor, ctx: TaskContext, text: str, workflow_path: str) -> ExecutorResult:
    wf = load_workflow(workflow_path)
    state = WorkflowState(
        workflow_id=str(uuid.uuid4()),
        workflow_type=wf.name,
        department=ctx.department,
        task_type=ctx.task_type,
        output_class=OutputClass.C,
        input_payload={"text": text, "subject_ids": []},
        audit_context={"workflow": wf.name},
    )
    return executor.run(ctx, wf, state)


def run_nestor(executor: WorkflowExecutor, ctx: TaskContext, text: str, subject_ids: list[str], workflow_path: str) -> ExecutorResult:
    wf = load_workflow(workflow_path)
    state = WorkflowState(
        workflow_id=str(uuid.uuid4()),
        workflow_type=wf.name,
        department=ctx.department,
        task_type=ctx.task_type,
        output_class=OutputClass.C,
        input_payload={"text": text, "subject_ids": subject_ids},
        audit_context={"workflow": wf.name},
    )
    return executor.run(ctx, wf, state)
