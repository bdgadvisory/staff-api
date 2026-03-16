import os
import time

import pytest

from staff.audit_logging.logger import AuditLogger
from staff.llm_router.capability_router import CapabilityRouter
from staff.llm_router.confidence import ConfidenceEngine, ConfidencePolicy
from staff.llm_router.escalation import EscalationEngine
from staff.llm_router.prompt_assembly import PromptAssemblyEngine, PromptAssemblyPolicy
from staff.llm_router.types import OutputClass, TaskContext
from staff.model_registry.registry import ProviderRegistry
from staff.providers.mock_adapter import MockAdapter
from staff.review_orchestrator.orchestrator import ReviewOrchestrator
from staff.workflows.executor import WorkflowExecutor
from staff.workflows.types import WorkflowDefinition, WorkflowState, WorkflowStep
from staff.llm_router.types import RetrievalBundle


def _executor_with_mock(*, behavior=None) -> WorkflowExecutor:
    registry = ProviderRegistry.from_yaml("staff/model_registry/default_registry.yaml")
    router = CapabilityRouter(registry=registry, department_policies={"scribe": {"default_output_class": "B"}})

    adapters = {
        "openai": MockAdapter("openai", behavior=behavior or {}),
        "google": MockAdapter("google"),
        "anthropic": MockAdapter("anthropic"),
    }

    return WorkflowExecutor(
        router=router,
        retrieval=None,  # unused in this test
        prompt_engine=PromptAssemblyEngine(PromptAssemblyPolicy()),
        adapters=adapters,
        reviewer=ReviewOrchestrator(adapters=adapters),
        confidence=ConfidenceEngine(ConfidencePolicy()),
        escalation=EscalationEngine(),
        audit=AuditLogger(sink_path=None),
    )


def test_retryable_rate_limit_halts_and_schedules_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("PROVIDER_MAX_RETRIES_PER_STEP", "3")

    behavior = {
        "failures_by_step_id": {
            "gen": {"times": 1, "error": "rate_limit", "retry_after_s": 2.0}
        }
    }
    ex = _executor_with_mock(behavior=behavior)

    wf = WorkflowDefinition(
        name="t",
        output_class=OutputClass.B,
        steps=[WorkflowStep(step_id="gen", step_type="generate", capability="reasoning_high")],
        department="scribe",
    )

    ctx = TaskContext(
        request_id="t",
        department="scribe",
        task_type="test",
        actor={"actor_type": "test", "actor_id": "t"},
        human_facing=True,
        privacy_class="internal",
        scope="test",
    )

    state = WorkflowState(
        workflow_id="wf1",
        workflow_type=wf.name,
        department="scribe",
        task_type="test",
        output_class=OutputClass.B,
        input_payload={"text": "hi", "scope": "test", "privacy_class": "internal"},
        audit_context={"workflow_path": "(direct)"},
    )

    # prepopulate retrieval bundle so generate step can run without calling retrieve
    state.retrieval_bundle = RetrievalBundle(graph_facts=[], semantic_chunks=[], episodic_events=[], constraints=[], citations=[], retrieval_meta={"source_object_ids": []})

    start = time.time()
    res = ex.run(ctx, wf, state)

    assert res.halted is True
    assert state.halt_reason in ("provider_rate_limit", "provider_overloaded")
    assert state.next_resume_at is not None
    assert state.next_resume_at >= start + 1.5  # should respect retry_after-ish

    last = state.step_artifacts[-1]
    assert last.status == "HALTED"
    assert last.next_action == "auto_resume_scheduled"
    assert last.retry_count is not None
