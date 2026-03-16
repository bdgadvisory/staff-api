from __future__ import annotations

import pytest

from staff.llm_router.types import OutputClass, TaskContext
from staff.workflows.executor import WorkflowExecutor
from staff.workflows.loader import load_workflow
from staff.workflows.types import WorkflowState


def _ctx() -> TaskContext:
    return TaskContext(
        request_id="req-rtp",
        department="nestor",
        task_type="reminder_message",
        actor={"actor_type": "agent", "actor_id": "nestor"},
        human_facing=True,
        privacy_class="internal",
        scope="family",
    )


def _state(audience=None) -> WorkflowState:
    payload = {"text": "message about pickup", "subject_ids": ["fennemijn"]}
    if audience is not None:
        payload["audience"] = audience

    return WorkflowState(
        workflow_id="wf-rtp",
        workflow_type="nestor_message",
        department="nestor",
        task_type="reminder_message",
        output_class=OutputClass.C,
        input_payload=payload,
    )


def _inject_restricted_to_parents(executor: WorkflowExecutor, monkeypatch):
    real = executor.retrieval.retrieve

    def wrapped(ctx, req):
        b = real(ctx, req)
        b.constraints.append({"constraint": "restricted_to_parents"})
        return b

    monkeypatch.setattr(executor.retrieval, "retrieve", wrapped)


def test_restricted_to_parents_missing_or_nonparent_audience_hard_stops_in_retrieve(executor: WorkflowExecutor, monkeypatch):
    """Case 1: restricted_to_parents present + missing (or non-parent) audience => hard-stop at retrieve."""
    wf = load_workflow("staff/examples/workflows/nestor_message.yaml")
    ctx = _ctx()

    _inject_restricted_to_parents(executor, monkeypatch)

    # missing audience
    state = _state(audience=None)
    res = executor.run(ctx, wf, state)

    assert res.halted is True
    retrieve_art = [a for a in state.step_artifacts if a.step_type == "retrieve"][0]
    assert retrieve_art.step_type == "retrieve"
    assert retrieve_art.status == "FAILED"
    assert retrieve_art.next_action == "restricted_to_parents"

    # explicit non-parent audience
    state2 = _state(audience="public")
    res2 = executor.run(ctx, wf, state2)

    assert res2.halted is True
    retrieve_art2 = [a for a in state2.step_artifacts if a.step_type == "retrieve"][0]
    assert retrieve_art2.status == "FAILED"
    assert retrieve_art2.next_action == "restricted_to_parents"


def test_restricted_to_parents_parents_audience_proceeds_past_retrieve(executor: WorkflowExecutor, monkeypatch):
    """Case 2: restricted_to_parents present + audience='parents' => retrieve succeeds; workflow proceeds."""
    wf = load_workflow("staff/examples/workflows/nestor_message.yaml")
    ctx = _ctx()

    _inject_restricted_to_parents(executor, monkeypatch)

    state = _state(audience="parents")
    res = executor.run(ctx, wf, state)

    # Should not fail at retrieve due to the constraint.
    retrieve_art = [a for a in state.step_artifacts if a.step_type == "retrieve"][0]
    assert retrieve_art.step_type == "retrieve"
    assert retrieve_art.status == "DONE"

    # Workflow should proceed to at least the next step.
    assert len(state.step_artifacts) >= 2
    # It may still halt later for other reasons, but not because retrieve hard-stopped.
    assert state.step_artifacts[0].next_action is None
