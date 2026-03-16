from __future__ import annotations

import copy

import pytest

from staff.llm_router.types import OutputClass, TaskContext
from staff.workflows.executor import WorkflowExecutor
from staff.workflows.loader import load_workflow
from staff.workflows.trace import build_trace
from staff.workflows.types import WorkflowState


def _ctx(department: str, task_type: str = "test") -> TaskContext:
    return TaskContext(
        request_id="req-1",
        department=department,
        task_type=task_type,
        actor={"actor_type": "agent", "actor_id": department},
        human_facing=True,
        privacy_class="internal",
        scope=department,
    )


def _state(wf_name: str, dept: str, task_type: str, output_class: OutputClass, text: str) -> WorkflowState:
    return WorkflowState(
        workflow_id="wf-1",
        workflow_type=wf_name,
        department=dept,
        task_type=task_type,
        output_class=output_class,
        input_payload={"text": text, "subject_ids": []},
    )


# ----------------- LinkedIn -----------------


def test_linkedin_halts_at_approval_gate(executor: WorkflowExecutor):
    wf = load_workflow("staff/examples/workflows/linkedin_post.yaml")
    ctx = _ctx("scribe", task_type="linkedin_post")
    state = _state(wf.name, "scribe", "linkedin_post", OutputClass.C, "draft a post")

    res = executor.run(ctx, wf, state)
    assert res.halted is True
    assert state.approval_status == "AWAITING_APPROVAL"
    assert state.final_output is None

    # deterministic order
    trace = build_trace(state)
    assert [t["step_id"] for t in trace] == [
        "retrieve",
        "route",
        "argument_draft",
        "quill_rewrite",
        "voice_pass",
        "editorial_critique",
        "approval_gate",
    ]

    # approval artifact has candidate output + sources
    approval_art = state.step_artifacts[-1]
    assert approval_art.step_type == "approval_gate"
    assert approval_art.status == "HALTED"
    assert approval_art.output_structured
    assert approval_art.output_structured["candidate_output"]
    assert approval_art.output_structured["source_object_ids"]


def test_linkedin_resume_approved_reaches_finalize(executor: WorkflowExecutor):
    wf = load_workflow("staff/examples/workflows/linkedin_post.yaml")
    ctx = _ctx("scribe", task_type="linkedin_post")
    state = _state(wf.name, "scribe", "linkedin_post", OutputClass.C, "draft a post")

    executor.run(ctx, wf, state)
    assert state.approval_status == "AWAITING_APPROVAL"

    # resume
    executor.resume_after_approval(state, approved=True, note="ok")
    res2 = executor.run(ctx, wf, state)
    assert res2.halted is False
    assert state.approval_status == "APPROVED"
    assert state.final_output is not None

    # ensure prior steps were not re-executed: we should resume at approval_gate
    # current_step should have been pointing at approval gate; on resume we run gate + finalize
    step_ids_after = [a.step_id for a in state.step_artifacts]
    assert step_ids_after.count("retrieve") == 1


def test_linkedin_resume_rejected_prevents_finalize(executor: WorkflowExecutor):
    wf = load_workflow("staff/examples/workflows/linkedin_post.yaml")
    ctx = _ctx("scribe", task_type="linkedin_post")
    state = _state(wf.name, "scribe", "linkedin_post", OutputClass.C, "draft a post")

    executor.run(ctx, wf, state)
    executor.resume_after_approval(state, approved=False, note="no")
    res2 = executor.run(ctx, wf, state)

    assert res2.halted is True
    assert state.approval_status == "REJECTED"
    assert state.final_output is None


def test_linkedin_sources_propagate_through_approval_to_finalize(executor: WorkflowExecutor):
    wf = load_workflow("staff/examples/workflows/linkedin_post.yaml")
    ctx = _ctx("scribe", task_type="linkedin_post")
    state = _state(wf.name, "scribe", "linkedin_post", OutputClass.C, "draft a post")

    executor.run(ctx, wf, state)
    src_ids = list(state.source_object_ids)
    cits = list(state.citations)

    approval_art = state.step_artifacts[-1]
    assert approval_art.output_structured["source_object_ids"] == src_ids
    assert approval_art.output_structured["citations"] == cits

    executor.resume_after_approval(state, approved=True)
    executor.run(ctx, wf, state)

    assert state.final_output
    final_art = state.step_artifacts[-1]
    assert final_art.step_type == "finalize"
    assert final_art.source_object_ids == src_ids
    assert final_art.citations == cits


def test_linkedin_class_c_finalize_fails_if_review_missing(executor: WorkflowExecutor):
    wf = load_workflow("staff/examples/workflows/linkedin_post.yaml")

    # Remove the critique step to simulate missing review.
    wf2 = copy.deepcopy(wf)
    wf2.steps = [s for s in wf2.steps if s.step_id != "editorial_critique"]

    # Also remove approval gate to isolate finalize failure reason.
    wf2.steps = [s for s in wf2.steps if s.step_id != "approval_gate"]

    ctx = _ctx("scribe", task_type="linkedin_post")
    state = _state(wf2.name, "scribe", "linkedin_post", OutputClass.C, "draft a post")

    res = executor.run(ctx, wf2, state)

    assert res.halted is True
    assert state.final_output is None
    assert state.step_artifacts[-1].step_type == "finalize"
    assert state.step_artifacts[-1].status == "FAILED"
    assert state.step_artifacts[-1].next_action == "missing_review"


# ----------------- Nestor -----------------


def test_nestor_class_c_requires_review_before_finalize(executor: WorkflowExecutor):
    wf = load_workflow("staff/examples/workflows/nestor_message.yaml")
    ctx = _ctx("nestor", task_type="reminder_message")
    state = _state(wf.name, "nestor", "reminder_message", OutputClass.C, "message spouse")

    # Disable approval gate so it doesn't halt.
    state.approval_status = "NOT_REQUIRED"

    res = executor.run(ctx, wf, state)
    # In this workflow, approval_gate required false, so should finalize.
    assert res.halted is False
    assert state.review_status == "REVIEWED"
    assert state.final_output is not None


def test_nestor_constraints_can_force_approval(executor: WorkflowExecutor, monkeypatch):
    wf = load_workflow("staff/examples/workflows/nestor_message.yaml")
    ctx = _ctx("nestor", task_type="reminder_message")
    state = _state(wf.name, "nestor", "reminder_message", OutputClass.C, "message spouse")

    # Monkeypatch retrieval to inject approval constraint
    real_retrieve = executor.retrieval.retrieve

    def forced(*args, **kwargs):
        b = real_retrieve(*args, **kwargs)
        b.constraints.append({"constraint": "requires_human_approval"})
        b.retrieval_meta["source_object_ids"].append("constraint/requires_human_approval")
        return b

    monkeypatch.setattr(executor.retrieval, "retrieve", forced)

    res = executor.run(ctx, wf, state)
    assert res.halted is True
    assert state.approval_status == "AWAITING_APPROVAL"


def test_nestor_retrieval_bundle_stored_once(executor: WorkflowExecutor):
    wf = load_workflow("staff/examples/workflows/nestor_message.yaml")
    ctx = _ctx("nestor", task_type="reminder_message")
    state = _state(wf.name, "nestor", "reminder_message", OutputClass.C, "message spouse")

    executor.run(ctx, wf, state)
    assert state.retrieval_bundle is not None

    retrieve_steps = [a for a in state.step_artifacts if a.step_type == "retrieve"]
    assert len(retrieve_steps) == 1


# ----------------- Foundry -----------------


def test_foundry_finalize_blocked_if_review_required_but_absent(executor: WorkflowExecutor):
    wf = load_workflow("staff/examples/workflows/foundry_build.yaml")

    # Remove critique step to simulate missing required review for Class C.
    wf2 = copy.deepcopy(wf)
    wf2.steps = [s for s in wf2.steps if s.step_type not in ("critique", "review")]

    # Also remove approval gate.
    wf2.steps = [s for s in wf2.steps if s.step_type != "approval_gate"]

    ctx = _ctx("foundry", task_type="code_change")
    state = _state(wf2.name, "foundry", "code_change", OutputClass.C, "refactor router")

    res = executor.run(ctx, wf2, state)
    assert res.halted is True
    assert state.step_artifacts[-1].step_type == "finalize"
    assert state.step_artifacts[-1].next_action == "missing_review"


# ----------------- QA -----------------


def test_qa_critique_statuses_are_representable(executor: WorkflowExecutor):
    wf = load_workflow("staff/examples/workflows/qa_critique.yaml")
    ctx = _ctx("qa", task_type="qa_critique")
    state = _state(wf.name, "qa", "qa_critique", OutputClass.B, "critique this")

    res = executor.run(ctx, wf, state)
    assert res.halted is False

    # The critique/review step outputs must carry status-like prefixes in output_text (mocked)
    critique = [a for a in state.step_artifacts if a.step_id == "critique"][0]
    assert critique.output_text is not None

    arbitration = [a for a in state.step_artifacts if a.step_id == "arbitration"][0]
    assert arbitration.output_text is not None


# ----------------- Global assertions -----------------


def test_halted_workflows_do_not_rerun_completed_steps_on_resume(executor: WorkflowExecutor):
    wf = load_workflow("staff/examples/workflows/linkedin_post.yaml")
    ctx = _ctx("scribe", task_type="linkedin_post")
    state = _state(wf.name, "scribe", "linkedin_post", OutputClass.C, "draft a post")

    executor.run(ctx, wf, state)
    pre = [a.step_id for a in state.step_artifacts]

    executor.resume_after_approval(state, approved=True)
    executor.run(ctx, wf, state)
    post = [a.step_id for a in state.step_artifacts]

    assert pre[:6] == post[:6]
    assert post.count("retrieve") == 1


def test_confidence_objects_present_on_required_steps(executor: WorkflowExecutor):
    wf = load_workflow("staff/examples/workflows/linkedin_post.yaml")
    ctx = _ctx("scribe", task_type="linkedin_post")
    state = _state(wf.name, "scribe", "linkedin_post", OutputClass.C, "draft a post")

    executor.run(ctx, wf, state)

    # steps before approval halt should include confidence on generate/rewrite/voice_pass/critique
    required_types = {"generate", "rewrite", "voice_pass", "critique"}
    for art in state.step_artifacts:
        if art.step_type in required_types:
            assert art.confidence is not None
            assert 0.0 <= art.confidence.confidence <= 1.0
            assert 0.0 <= art.confidence.ambiguity_score <= 1.0
            assert 0.0 <= art.confidence.source_quality <= 1.0


def test_low_confidence_review_outcome_blocks_finalize(executor: WorkflowExecutor):
    # Force rewrite-required on editorial_critique
    executor.adapters["anthropic"].behavior["qa_status_by_step_id"]["editorial_critique"] = "REWRITE_REQUIRED"

    wf = load_workflow("staff/examples/workflows/linkedin_post.yaml")
    ctx = _ctx("scribe", task_type="linkedin_post")
    state = _state(wf.name, "scribe", "linkedin_post", OutputClass.C, "draft a post")

    executor.run(ctx, wf, state)
    executor.resume_after_approval(state, approved=True)
    res2 = executor.run(ctx, wf, state)

    assert res2.halted is True
    last = state.step_artifacts[-1]
    assert last.step_type == "finalize"
    assert last.status == "FAILED"
    assert last.confidence is not None
    assert last.confidence.confidence <= 0.45
