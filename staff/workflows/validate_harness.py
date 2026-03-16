from __future__ import annotations

import argparse

import yaml

from staff.audit_logging.logger import AuditLogger
from staff.llm_router.capability_router import CapabilityRouter
from staff.llm_router.confidence import ConfidenceEngine, ConfidencePolicy
from staff.llm_router.escalation import EscalationEngine
from staff.llm_router.prompt_assembly import PromptAssemblyEngine, PromptAssemblyPolicy
from staff.llm_router.retrieval_contract import RetrievalClient
from staff.llm_router.types import TaskContext
from staff.model_registry.registry import ProviderRegistry
from staff.providers.mock_adapter import MockAdapter
from staff.review_orchestrator.orchestrator import ReviewOrchestrator
from staff.workflows.executor import WorkflowExecutor
from staff.workflows.loader import load_workflow
from staff.workflows.trace import format_trace
from staff.workflows.types import WorkflowState


def build_executor() -> WorkflowExecutor:
    registry = ProviderRegistry.from_yaml("staff/model_registry/default_registry.yaml")
    with open("staff/policy/department_policies.yaml", "r", encoding="utf-8") as f:
        dept = yaml.safe_load(f)

    router = CapabilityRouter(registry=registry, department_policies=dept)
    retrieval = RetrievalClient()  # controlled via env STAFF_MEMORY_SERVICE_MODE=http|mock

    adapters = {
        "openai": MockAdapter("openai"),
        "google": MockAdapter("google"),
        "anthropic": MockAdapter("anthropic", behavior={"default_prefix": "[MOCK_REVIEW]"}),
    }
    reviewer = ReviewOrchestrator(adapters=adapters)

    return WorkflowExecutor(
        router=router,
        retrieval=retrieval,
        prompt_engine=PromptAssemblyEngine(PromptAssemblyPolicy()),
        adapters=adapters,
        reviewer=reviewer,
        confidence=ConfidenceEngine(ConfidencePolicy()),
        escalation=EscalationEngine(),
        audit=AuditLogger(sink_path=None),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True, help="Path to workflow YAML")
    ap.add_argument("--department", required=False, help="Capability department (defaults to workflow metadata)")
    ap.add_argument("--task-type", required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--approve", action="store_true")
    args = ap.parse_args()

    wf = load_workflow(args.workflow)
    department = args.department or (wf.department or "scribe")

    ctx = TaskContext(
        request_id="harness",
        department=department,
        task_type=args.task_type,
        actor={"actor_type": "agent", "actor_id": department},
        human_facing=True,
        privacy_class="internal",
        scope=args.department,
    )

    state = WorkflowState(
        workflow_id="harness-wf",
        workflow_type=wf.name,
        department=department,
        task_type=args.task_type,
        output_class=wf.output_class,
        input_payload={"text": args.text, "subject_ids": []},
    )

    ex = build_executor()
    res = ex.run(ctx, wf, state)
    print(format_trace(state))

    if res.halted and state.approval_status == "AWAITING_APPROVAL" and args.approve:
        print("\n--- resuming after approval ---\n")
        ex.resume_after_approval(state, approved=True)
        ex.run(ctx, wf, state)
        print(format_trace(state))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
