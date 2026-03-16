import os

from staff.workflows.runtime import build_executor_from_env
from staff.llm_router.types import OutputClass, TaskContext, RetrievalBundle
from staff.workflows.types import WorkflowDefinition, WorkflowState, WorkflowStep


def test_cooldown_state_present_on_halt(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("STAFF_LIVE_MODE", "0")

    ex = build_executor_from_env(live_mode=False)
    ex.adapters["openai"].behavior = {
        "failures_by_step_id": {"gen": {"times": 1, "error": "rate_limit", "retry_after_s": 0.01}}
    }

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
        workflow_id="wf3",
        workflow_type=wf.name,
        department="scribe",
        task_type="test",
        output_class=OutputClass.B,
        input_payload={"text": "hi", "scope": "test", "privacy_class": "internal"},
        audit_context={"workflow_path": "(direct)"},
    )
    state.retrieval_bundle = RetrievalBundle(graph_facts=[], semantic_chunks=[], episodic_events=[], constraints=[], citations=[], retrieval_meta={"source_object_ids": []})

    res = ex.run(ctx, wf, state)
    assert res.halted is True
    art = state.step_artifacts[-1]
    assert art.status == "HALTED"
    assert art.cooldown_state is not None
    assert art.cooldown_state.get("provider") == "openai"
