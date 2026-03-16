import os
import time

import pytest

from staff.llm_router.types import OutputClass, TaskContext, RetrievalBundle
from staff.workflows.types import WorkflowDefinition, WorkflowState, WorkflowStep
from staff.workflows.runtime import build_executor_from_env
from staff.workflows.resume_tick import workflow_resume_tick


def test_checkpoint_written_and_resume_skips_done_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("STAFF_LIVE_MODE", "0")

    # Build executor in mock mode, but inject a one-time 429 on gen
    ex = build_executor_from_env(live_mode=False)
    ex.adapters["openai"].behavior = {
        "failures_by_step_id": {"gen": {"times": 1, "error": "rate_limit", "retry_after_s": 0.1}}
    }

    wf_path = tmp_path / "wf.yaml"
    wf_path.write_text(
        """
name: wf
output_class: B
pipeline:
  - step: gen
    capability: reasoning_high
""".lstrip()
    )

    from staff.workflows.loader import load_workflow

    wf = load_workflow(str(wf_path))

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
        workflow_id="wf2",
        workflow_type=wf.name,
        department="scribe",
        task_type="test",
        output_class=OutputClass.B,
        input_payload={"text": "hi", "scope": "test", "privacy_class": "internal"},
        audit_context={"workflow_path": str(wf_path)},
    )
    state.retrieval_bundle = RetrievalBundle(graph_facts=[], semantic_chunks=[], episodic_events=[], constraints=[], citations=[], retrieval_meta={"source_object_ids": []})

    res = ex.run(ctx, wf, state)
    assert res.halted is True

    ckpt_file = tmp_path / "wf2.json"
    assert ckpt_file.exists()

    # Force due and run tick resume. On resume, the injected failure has been consumed.
    time.sleep(0.12)
    out = workflow_resume_tick(now_ts=time.time() + 10)
    assert out["processed"] >= 1
    assert out["resumed"] >= 1
