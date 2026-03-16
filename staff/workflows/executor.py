from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import time

from staff.audit_logging.logger import AuditLogger
from staff.llm_router.capability_router import CapabilityRouter
from staff.llm_router.confidence import ConfidenceEngine
from staff.llm_router.escalation import EscalationEngine
from staff.llm_router.prompt_assembly import PromptAssemblyEngine
from staff.llm_router.retrieval_contract import RetrievalClient, RetrievalRequest
from staff.llm_router.task_classifier import TaskClassifier
from staff.llm_router.types import LLMResult, ModelSelection, OutputClass, TaskContext
from staff.providers.base import LLMCall, ProviderAdapter
from staff.review_orchestrator.orchestrator import ReviewOrchestrator, ReviewStage
from staff.workflows.confidence import StepConfidenceDeriver
from staff.workflows.types import StepArtifact, WorkflowDefinition, WorkflowState, WorkflowStep
from staff.workflows.checkpoints import FileCheckpointStore, WorkflowCheckpointStore
from staff.workflows.budgets import WorkflowBudgets
from staff.providers.retry import RetryPolicy, compute_backoff, is_retryable_error
from staff.providers.throttle import ProviderThrottleState
from staff.audit_logging import events as audit_events


@dataclass(frozen=True)
class ExecutorResult:
    state: WorkflowState
    halted: bool


class WorkflowExecutor:
    """Deterministic multi-step workflow executor.

    Core properties:
    - Executes YAML-defined steps in order, emitting StepArtifacts.
    - Enforces OutputClass A/B/C rules *operationally*.
    - Supports approval gate halting + later resumption.
    - Retrieval is explicit and always via RetrievalClient HTTP boundary.
    """

    def __init__(
        self,
        *,
        router: CapabilityRouter,
        retrieval: RetrievalClient,
        prompt_engine: PromptAssemblyEngine,
        adapters: dict[str, ProviderAdapter],
        reviewer: ReviewOrchestrator,
        confidence: ConfidenceEngine,
        escalation: EscalationEngine,
        audit: AuditLogger,
        classifier: TaskClassifier | None = None,
        checkpoint_store: WorkflowCheckpointStore | None = None,
        throttle: ProviderThrottleState | None = None,
        retry_policy: RetryPolicy | None = None,
        budgets: WorkflowBudgets | None = None,
    ):
        self.router = router
        self.retrieval = retrieval
        self.prompt_engine = prompt_engine
        self.adapters = adapters
        self.reviewer = reviewer
        self.confidence = confidence
        self._conf = StepConfidenceDeriver(confidence)
        self.escalation = escalation
        self.audit = audit
        self.classifier = classifier or TaskClassifier()

        self.checkpoints: WorkflowCheckpointStore = checkpoint_store or FileCheckpointStore()
        self.throttle: ProviderThrottleState = throttle or ProviderThrottleState()
        self.retry_policy: RetryPolicy = retry_policy or RetryPolicy(
            max_retries=int(__import__("os").environ.get("PROVIDER_MAX_RETRIES_PER_STEP", "6")),
            base_delay_s=float(__import__("os").environ.get("PROVIDER_BACKOFF_BASE_S", "1.0")),
            max_delay_s=float(__import__("os").environ.get("PROVIDER_BACKOFF_MAX_S", "60.0")),
            jitter=0.25,
            respect_retry_after=True,
        )
        self.budgets: WorkflowBudgets = budgets or WorkflowBudgets.from_env()

    def run(self, ctx: TaskContext, wf: WorkflowDefinition, state: WorkflowState) -> ExecutorResult:
        state.halted = False
        state.halt_reason = None

        steps = wf.steps
        while state.current_step < len(steps):
            step = steps[state.current_step]

            # Structural fix: prevent replay on resume.
            existing = state.artifact_for_step(step.step_id)
            if existing and existing.status == "DONE":
                state.current_step += 1
                continue

            art = self._dispatch_step(ctx, wf, state, step)
            state.step_artifacts.append(art)

            if art.status in ("HALTED", "FAILED"):
                state.halted = True
                state.halt_reason = art.halt_reason or art.next_action or art.status
                return ExecutorResult(state=state, halted=True)

            state.current_step += 1

        return ExecutorResult(state=state, halted=False)

    def resume_after_approval(self, state: WorkflowState, approved: bool, note: str | None = None) -> None:
        if state.approval_status != "AWAITING_APPROVAL":
            return
        state.approval_status = "APPROVED" if approved else "REJECTED"
        if note:
            state.audit_context.setdefault("approval_notes", []).append(note)
        state.halted = False
        state.halt_reason = None

    # --- step dispatch ---

    def _dispatch_step(
        self, ctx: TaskContext, wf: WorkflowDefinition, state: WorkflowState, step: WorkflowStep
    ) -> StepArtifact:
        stype = step.step_type
        if stype == "classify":
            return self._step_classify(ctx, state, step)
        if stype == "retrieve":
            return self._step_retrieve(ctx, state, step)
        if stype == "route":
            return self._step_route(ctx, state, step)
        if stype in ("generate", "rewrite", "voice_pass"):
            return self._step_llm_generate(ctx, state, step, kind=stype)
        if stype in ("review", "critique"):
            return self._step_review(ctx, state, step)
        if stype == "approval_gate":
            return self._step_approval_gate(ctx, wf, state, step)
        if stype == "audit":
            return self._step_audit(ctx, state, step)
        if stype == "finalize":
            return self._step_finalize(ctx, wf, state, step)

        return StepArtifact(step_id=step.step_id, step_type=stype, status="FAILED", next_action="unknown_step_type")

    # --- step implementations ---

    def _step_classify(self, ctx: TaskContext, state: WorkflowState, step: WorkflowStep) -> StepArtifact:
        text = state.input_payload.get("text") or state.input_payload.get("query") or ""
        cls = self.classifier.classify(ctx, text)
        state.audit_context["classification"] = {"triggers": cls.triggers, "risk_level": cls.risk_level}

        return StepArtifact(
            step_id=step.step_id,
            step_type="classify",
            status="DONE",
            output_structured={"output_class": cls.output_class.value, "risk_level": cls.risk_level, "triggers": cls.triggers},
            next_action=None,
        )

    def _step_retrieve(self, ctx: TaskContext, state: WorkflowState, step: WorkflowStep) -> StepArtifact:
        text = state.input_payload.get("text") or state.input_payload.get("query") or ""

        req = RetrievalRequest(
            agent_id=str(ctx.actor.get("actor_id") or ctx.department),
            department=ctx.department,
            task_type=ctx.task_type,
            query=text,
            scope=ctx.scope,
            subject_ids=state.input_payload.get("subject_ids", []),
            output_class=state.output_class,
            max_graph_facts=20,
            max_semantic_chunks=6,
            max_episodic_events=12,
            include_citations=True,
        )
        bundle = self.retrieval.retrieve(ctx, req)
        state.retrieval_bundle = bundle
        state.set_sources_from_bundle()

        # Hard-stop constraints
        for c in bundle.constraints:
            if c.get("constraint") == "department_scope_violation":
                return StepArtifact(
                    step_id=step.step_id,
                    step_type="retrieve",
                    status="FAILED",
                    output_structured={"error": "department_scope_violation", "details": c},
                    citations=state.citations,
                    source_object_ids=state.source_object_ids,
                    next_action="department_scope_violation",
                )

        # Context visibility enforcement: restricted_to_parents is not just a send/recipient rule.
        for c in bundle.constraints:
            if c.get("constraint") == "restricted_to_parents":
                audience = state.input_payload.get("audience")
                if audience not in ("parents", "parent"):
                    return StepArtifact(
                        step_id=step.step_id,
                        step_type="retrieve",
                        status="FAILED",
                        output_structured={
                            "error": "restricted_to_parents",
                            "details": c,
                            "note": "Workflow context restricted to parents; set input_payload.audience='parents' to proceed.",
                        },
                        citations=state.citations,
                        source_object_ids=state.source_object_ids,
                        next_action="restricted_to_parents",
                    )

        return StepArtifact(
            step_id=step.step_id,
            step_type="retrieve",
            status="DONE",
            output_structured={
                "graph_facts": len(bundle.graph_facts),
                "semantic_chunks": len(bundle.semantic_chunks),
                "episodic_events": len(bundle.episodic_events),
                "constraints": len(bundle.constraints),
                "retrieval_meta": bundle.retrieval_meta,
            },
            citations=state.citations,
            source_object_ids=state.source_object_ids,
        )

    def _step_route(self, ctx: TaskContext, state: WorkflowState, step: WorkflowStep) -> StepArtifact:
        intent = {
            "output_class": state.output_class.value,
            "triggers": (state.audit_context.get("classification") or {}).get("triggers", []),
        }
        plan = self.router.route(ctx, intent=intent)
        state.audit_context["route_plan"] = {
            "selected_capabilities": [c for c in plan.selected_capabilities],
            "primary": plan.primary.provider_key,
            "reviewers": [r.provider_key for r in plan.reviewers],
        }

        return StepArtifact(
            step_id=step.step_id,
            step_type="route",
            status="DONE",
            output_structured={
                "output_class": plan.output_class.value,
                "risk_level": plan.risk_level,
                "selected_capabilities": plan.selected_capabilities,
                "primary": {
                    "provider": plan.primary.provider,
                    "model": plan.primary.model,
                    "capability": plan.primary.capability,
                },
                "reviewers": [
                    {"provider": r.provider, "model": r.model, "capability": r.capability} for r in plan.reviewers
                ],
            },
            citations=state.citations,
            source_object_ids=state.source_object_ids,
        )

    def _select_model(self, ctx: TaskContext, capability: str | None) -> ModelSelection:
        # Route by explicit capability if present; otherwise use department policy default.
        if capability:
            return self.router.registry.resolve(capability)  # type: ignore[arg-type]

        plan = self.router.route(ctx, intent={"output_class": "B"})
        return plan.primary

    def _call_provider_with_retry_and_checkpoint(
        self,
        *,
        ctx: TaskContext,
        state: WorkflowState,
        step: WorkflowStep,
        selection: ModelSelection,
        call: LLMCall,
    ) -> LLMResult | StepArtifact:
        """Centralized provider call wrapper.

        Returns:
          - LLMResult on success
          - StepArtifact(status=HALTED/FAILED) on structured halts
        """

        provider = selection.provider
        model = selection.model

        # Budgets: calls per workflow
        state.workflow_call_counts["total"] = int(state.workflow_call_counts.get("total") or 0)
        if state.workflow_call_counts["total"] >= self.budgets.max_provider_calls_per_workflow:
            state.halted = True
            state.halt_reason = "budget_exhausted"
            return StepArtifact(
                step_id=step.step_id,
                step_type=step.step_type,
                status="FAILED",
                halt_reason="budget_exhausted",
                provider_name=provider,
                model_name=model,
                next_action="manual_intervention_required",
            )

        adapter = self.adapters.get(provider)
        if not adapter:
            state.halted = True
            state.halt_reason = "missing_adapter"
            return StepArtifact(
                step_id=step.step_id,
                step_type=step.step_type,
                status="FAILED",
                halt_reason="missing_adapter",
                provider_name=provider,
                model_name=model,
                next_action="missing_adapter",
            )

        # Retry tracking
        rcounts: dict[str, int] = state.retry_state.get("retry_count_by_step") or {}
        retry_count = int(rcounts.get(step.step_id) or 0)

        # checkpoint BEFORE external call
        call_spec = {
            "provider": provider,
            "model": model,
            "step_id": step.step_id,
            "step_type": step.step_type,
            "max_tokens": call.max_tokens,
            "temperature": call.temperature,
        }
        ckpt_path = self.checkpoints.save_pre_call(state.workflow_id, state, step.step_id, call_spec)
        audit_events.log_checkpoint_event(workflow_id=state.workflow_id, step_id=step.step_id, stage="pre_call", checkpoint_path=ckpt_path)

        # throttle
        self.throttle.acquire(provider, model)
        try:
            while True:
                try:
                    out = adapter.complete(call)

                    # bump budgets/counters on success
                    state.workflow_call_counts["total"] = state.workflow_call_counts["total"] + 1
                    bp = state.workflow_call_counts.get("by_provider") or {}
                    bp[provider] = int(bp.get(provider) or 0) + 1
                    state.workflow_call_counts["by_provider"] = bp
                    bm = state.workflow_call_counts.get("by_model") or {}
                    bm[model] = int(bm.get(model) or 0) + 1
                    state.workflow_call_counts["by_model"] = bm

                    return out

                except Exception as e:
                    retryable, meta = is_retryable_error(e)
                    retry_after_s = meta.get("retry_after_s")

                    if not retryable:
                        state.halted = True
                        state.halt_reason = "non_retryable_provider_error"
                        state.retry_state["last_error"] = {"error": repr(e), **meta}
                        state.retry_state["provider_name"] = provider
                        state.retry_state["model_name"] = model
                        return StepArtifact(
                            step_id=step.step_id,
                            step_type=step.step_type,
                            status="FAILED",
                            halt_reason="non_retryable_provider_error",
                            provider_name=provider,
                            model_name=model,
                            retry_count=retry_count,
                            next_action="manual_intervention_required",
                            output_structured={"error": repr(e), **meta},
                        )

                    # retry budget
                    if retry_count >= self.budgets.max_retries_per_step:
                        state.halted = True
                        state.halt_reason = "provider_retry_budget_exhausted"
                        state.retry_state["last_error"] = {"error": repr(e), **meta}
                        state.retry_state["provider_name"] = provider
                        state.retry_state["model_name"] = model
                        rcounts[step.step_id] = retry_count
                        state.retry_state["retry_count_by_step"] = rcounts
                        return StepArtifact(
                            step_id=step.step_id,
                            step_type=step.step_type,
                            status="HALTED",
                            halt_reason="provider_retry_budget_exhausted",
                            provider_name=provider,
                            model_name=model,
                            retry_count=retry_count,
                            next_action="manual_intervention_required",
                            output_structured={"error": repr(e), **meta},
                        )

                    # compute backoff + cooldown
                    backoff_s = compute_backoff(self.retry_policy, retry_count, retry_after=retry_after_s)
                    cooldown_state = self.throttle.note_rate_limit(provider, model, retry_after_s)
                    audit_events.log_throttle_event(
                        workflow_id=state.workflow_id, provider=provider, model=model, cooldown_state=cooldown_state
                    )

                    retry_count += 1
                    rcounts[step.step_id] = retry_count
                    state.retry_state["retry_count_by_step"] = rcounts
                    state.retry_state["last_error"] = {"error": repr(e), **meta}
                    state.retry_state["provider_name"] = provider
                    state.retry_state["model_name"] = model

                    # HALT and schedule tick-based auto-resume
                    state.halted = True
                    state.halt_reason = "provider_rate_limit" if meta.get("http_status") == 429 else "provider_overloaded"
                    state.next_resume_at = time.time() + float(backoff_s)

                    audit_events.log_retry_event(
                        workflow_id=state.workflow_id,
                        step_id=step.step_id,
                        provider=provider,
                        model=model,
                        error_type=str(meta.get("error_type")),
                        retry_count=retry_count,
                        backoff_s=float(backoff_s),
                        auto_resume_scheduled=True,
                    )
                    audit_events.log_auto_resume_event(
                        workflow_id=state.workflow_id,
                        step_id=step.step_id,
                        scheduled_for_ts=float(state.next_resume_at),
                        resumed_from_checkpoint=True,
                    )

                    # persist halt state so tick can resume
                    halt_art = StepArtifact(
                        step_id=step.step_id,
                        step_type=step.step_type,
                        status="HALTED",
                        halt_reason=state.halt_reason,
                        provider_name=provider,
                        model_name=model,
                        retry_count=retry_count,
                        backoff_s=float(backoff_s),
                        auto_resume_scheduled=True,
                        resumed_from_checkpoint=True,
                        cooldown_state=cooldown_state,
                        next_action="auto_resume_scheduled",
                        output_structured={"error": repr(e), **meta},
                    )
                    post_path = self.checkpoints.save_post_call(state.workflow_id, state, step.step_id, halt_art)
                    audit_events.log_checkpoint_event(
                        workflow_id=state.workflow_id,
                        step_id=step.step_id,
                        stage="halted",
                        checkpoint_path=post_path,
                    )

                    return halt_art
        finally:
            self.throttle.release(provider, model)


    def _step_llm_generate(self, ctx: TaskContext, state: WorkflowState, step: WorkflowStep, kind: str) -> StepArtifact:
        if not state.retrieval_bundle:
            return StepArtifact(step_id=step.step_id, step_type=kind, status="FAILED", next_action="missing_retrieval")

        selection = self._select_model(ctx, step.capability)
        adapter = self.adapters.get(selection.provider)
        if not adapter:
            return StepArtifact(step_id=step.step_id, step_type=kind, status="FAILED", next_action="missing_adapter")

        # Compose input as: previous output (if any) + original user intent.
        user_text = state.last_output_text() or (state.input_payload.get("text") or "")

        prompt = self.prompt_engine.assemble(ctx, user_input=user_text, bundle=state.retrieval_bundle)
        call = LLMCall(
            model=selection.model,
            messages=prompt.messages,
            temperature=0.3 if kind in ("rewrite", "voice_pass") else 0.2,
            max_tokens=min(2000, prompt.token_budget // 3),
            metadata={
                "workflow_id": state.workflow_id,
                "step_id": step.step_id,
                "step_type": kind,
                "department": ctx.department,
                "task_type": ctx.task_type,
            },
        )

        res = self._call_provider_with_retry_and_checkpoint(
            ctx=ctx,
            state=state,
            step=step,
            selection=selection,
            call=call,
        )
        if isinstance(res, StepArtifact):
            # Structured halt/failure: propagate, but keep LLM step metadata.
            res.selected_capability = selection.capability
            res.selected_provider = selection.provider
            res.selected_model = selection.model
            res.citations = state.citations
            res.source_object_ids = state.source_object_ids
            return res

        out: LLMResult = res

        conf = self._conf.derive(ctx=ctx, state=state, step_type=kind)

        # per-step audit (important for live provider observability)
        from staff.llm_router.types import RetrievalBundle

        self.audit.log(
            ctx=ctx,
            selection=selection,
            confidence=conf,
            review_status=state.review_status,
            escalation_chain=conf.escalation_reason,
            retrieval=state.retrieval_bundle or RetrievalBundle(),
            source_object_ids=state.source_object_ids,
            workflow_id=state.workflow_id,
            step_id=step.step_id,
            step_type=kind,
            latency_ms=out.latency_ms,
            cost_estimate=out.cost_estimate,
        )

        art = StepArtifact(
            step_id=step.step_id,
            step_type=kind,  # generate|rewrite|voice_pass
            status="DONE",
            selected_capability=selection.capability,
            selected_provider=selection.provider,
            selected_model=selection.model,
            input_refs=["retrieval_bundle", "prior_output" if state.last_output_text() else "input_payload"],
            output_text=out.text,
            output_structured=None,
            confidence=conf,
            needs_review=conf.needs_review,
            citations=state.citations,
            source_object_ids=state.source_object_ids,
        )

        # checkpoint AFTER success
        state.checkpoint["last_completed_step_index"] = state.current_step
        state.checkpoint["last_completed_step_id"] = step.step_id
        post_path = self.checkpoints.save_post_call(state.workflow_id, state, step.step_id, art)
        audit_events.log_checkpoint_event(workflow_id=state.workflow_id, step_id=step.step_id, stage="post_call", checkpoint_path=post_path)

        return art

    def _review_required(self, ctx: TaskContext, state: WorkflowState) -> bool:
        # Enforce class rules.
        if state.output_class == OutputClass.C:
            return True

        # For B: if confidence engine would have required review. In v1 we rely on classifier triggers.
        triggers = (state.audit_context.get("classification") or {}).get("triggers", [])
        if any(t in ("public_publication", "emotional_sensitivity_detected", "health_related") for t in triggers):
            return True

        # Otherwise optional.
        return False

    def _step_review(self, ctx: TaskContext, state: WorkflowState, step: WorkflowStep) -> StepArtifact:
        # Review/critique operate on latest output.
        draft = state.last_output_text()
        if not draft:
            return StepArtifact(step_id=step.step_id, step_type=step.step_type, status="FAILED", next_action="missing_draft")

        # Critique/review steps should run by default when present for QA workflows.
        if ctx.department != "qa" and step.step_type != "critique" and not self._review_required(ctx, state) and step.when != "always":
            return StepArtifact(step_id=step.step_id, step_type=step.step_type, status="SKIPPED")

        selection = self._select_model(ctx, step.capability)  # usually editorial_review capability

        instruction = step.instruction or (
            "You are a critical reviewer. Identify weaknesses, missing constraints, tone risks, and required rewrites. "
            "Return either PASS, PASS_WITH_WARNINGS, REWRITE_REQUIRED, or ESCALATE_TO_HUMAN, plus a corrected version if needed."
        )

        # Direct provider call (review) through the centralized retry/checkpoint wrapper.
        call = LLMCall(
            model=selection.model,
            messages=[
                {"role": "system", "content": instruction},
                {"role": "user", "content": draft},
            ],
            temperature=0.2,
            max_tokens=1200,
            metadata={
                "workflow_id": state.workflow_id,
                "step_id": step.step_id,
                "step_type": step.step_type,
                "department": ctx.department,
                "task_type": ctx.task_type,
            },
        )

        res = self._call_provider_with_retry_and_checkpoint(
            ctx=ctx,
            state=state,
            step=step,
            selection=selection,
            call=call,
        )
        if isinstance(res, StepArtifact):
            res.selected_capability = selection.capability
            res.selected_provider = selection.provider
            res.selected_model = selection.model
            res.citations = state.citations
            res.source_object_ids = state.source_object_ids
            state.review_status = "ESCALATE_TO_HUMAN"
            return res

        review_out = res

        # Minimal status parse (supports QA employee statuses)
        head = (review_out.text or "").strip().split(":", 1)[0].strip()
        if head in ("PASS", "PASS_WITH_WARNINGS"):
            state.review_status = "REVIEWED"
        elif head == "REWRITE_REQUIRED":
            state.review_status = "REWRITE_REQUIRED"
        elif head == "ESCALATE_TO_HUMAN":
            state.review_status = "ESCALATE_TO_HUMAN"
        else:
            state.review_status = "REVIEWED"

        conf = self._conf.derive(ctx=ctx, state=state, step_type=step.step_type, review_outcome=head)

        from staff.llm_router.types import RetrievalBundle

        self.audit.log(
            ctx=ctx,
            selection=selection,
            confidence=conf,
            review_status=state.review_status,
            escalation_chain=conf.escalation_reason,
            retrieval=state.retrieval_bundle or RetrievalBundle(),
            source_object_ids=state.source_object_ids,
            workflow_id=state.workflow_id,
            step_id=step.step_id,
            step_type=step.step_type,
            latency_ms=review_out.latency_ms,
            cost_estimate=review_out.cost_estimate,
        )

        art = StepArtifact(
            step_id=step.step_id,
            step_type=step.step_type,
            status="DONE",
            selected_capability=selection.capability,
            selected_provider=selection.provider,
            selected_model=selection.model,
            input_refs=["prior_output"],
            output_text=review_out.text,
            confidence=conf,
            needs_review=conf.needs_review,
            citations=state.citations,
            source_object_ids=state.source_object_ids,
            next_action=None,
        )

        state.review_pass_count += 1
        state.checkpoint["last_completed_step_index"] = state.current_step
        state.checkpoint["last_completed_step_id"] = step.step_id
        post_path = self.checkpoints.save_post_call(state.workflow_id, state, step.step_id, art)
        audit_events.log_checkpoint_event(workflow_id=state.workflow_id, step_id=step.step_id, stage="post_call", checkpoint_path=post_path)

        return art

    def _approval_required(self, wf: WorkflowDefinition, state: WorkflowState) -> bool:
        # Workflow-configured requirement is authoritative.
        # Additionally, allow constraints to force approval.
        if state.output_class == OutputClass.C:
            # default: approval required if workflow includes a required approval gate
            pass

        # check constraints in retrieval bundle
        if state.retrieval_bundle:
            for c in state.retrieval_bundle.constraints:
                if c.get("constraint") in (
                    "requires_parent_approval",
                    "requires_human_approval",
                    "requires_bart_approval",
                ):
                    return True

        return False

    def _step_approval_gate(self, ctx: TaskContext, wf: WorkflowDefinition, state: WorkflowState, step: WorkflowStep) -> StepArtifact:
        required = bool(step.required)
        required = required or self._approval_required(wf, state)

        if not required:
            state.approval_status = "NOT_REQUIRED"
            return StepArtifact(step_id=step.step_id, step_type="approval_gate", status="SKIPPED")

        # If already approved, pass through.
        if state.approval_status == "APPROVED":
            return StepArtifact(step_id=step.step_id, step_type="approval_gate", status="DONE", next_action=None)

        # If rejected, halt.
        if state.approval_status == "REJECTED":
            return StepArtifact(step_id=step.step_id, step_type="approval_gate", status="FAILED", next_action="rejected")

        # Otherwise halt and await.
        state.approval_status = "AWAITING_APPROVAL"
        state.halted = True

        return StepArtifact(
            step_id=step.step_id,
            step_type="approval_gate",
            status="HALTED",
            output_structured={
                "candidate_output": state.last_output_text(),
                "citations": state.citations,
                "source_object_ids": state.source_object_ids,
            },
            next_action="awaiting_approval",
        )

    def _step_audit(self, ctx: TaskContext, state: WorkflowState, step: WorkflowStep) -> StepArtifact:
        # Per-step audit: log minimal record (workflow + step + class + sources)
        last = state.step_artifacts[-1] if state.step_artifacts else None
        provider = last.selected_provider if last else None
        model = last.selected_model if last else None
        capability = last.selected_capability if last else None

        # We don't have a full ConfidenceReport per-step yet; attach at finalization.
        dummy_conf = self.confidence.evaluate(
            ctx,
            output_class=state.output_class,
            risk_level="medium",
            ambiguity_score=0.1,
            source_quality=0.7,
            base_confidence=0.85,
            escalation_reason=[],
        )

        selection = ModelSelection(
            capability=capability or "reasoning_medium",  # type: ignore[assignment]
            provider_key="workflow.executor",
            provider=provider or "unknown",
            model=model or "unknown",
            lane="",
        )

        from staff.llm_router.types import RetrievalBundle

        self.audit.log(
            ctx=ctx,
            selection=selection,
            confidence=dummy_conf,
            review_status=state.review_status,
            escalation_chain=[],
            retrieval=state.retrieval_bundle or RetrievalBundle(),
            source_object_ids=state.source_object_ids,
            latency_ms=None,
            cost_estimate=None,
        )

        return StepArtifact(step_id=step.step_id, step_type="audit", status="DONE")

    def _step_finalize(self, ctx: TaskContext, wf: WorkflowDefinition, state: WorkflowState, step: WorkflowStep) -> StepArtifact:
        conf = self._conf.derive(ctx=ctx, state=state, step_type="finalize")

        # Enforce class conditions.
        # Enforce do_not_contact_directly: block finalize/send path.
        if state.retrieval_bundle:
            for c in state.retrieval_bundle.constraints:
                if c.get("constraint") == "do_not_contact_directly":
                    conf = self._conf.derive(ctx=ctx, state=state, step_type="finalize", base_conf_override=0.20)
                    return StepArtifact(
                        step_id=step.step_id,
                        step_type="finalize",
                        status="FAILED",
                        confidence=conf,
                        needs_review=True,
                        output_structured={"error": "do_not_contact_directly", "details": c},
                        citations=state.citations,
                        source_object_ids=state.source_object_ids,
                        next_action="do_not_contact_directly",
                    )

        if state.output_class == OutputClass.C:
            if state.review_status == "NOT_REVIEWED":
                return StepArtifact(
                    step_id=step.step_id,
                    step_type="finalize",
                    status="FAILED",
                    confidence=conf,
                    needs_review=True,
                    next_action="missing_review",
                )
            if state.review_status in ("REWRITE_REQUIRED", "ESCALATE_TO_HUMAN"):
                return StepArtifact(
                    step_id=step.step_id,
                    step_type="finalize",
                    status="FAILED",
                    confidence=conf,
                    needs_review=True,
                    next_action=f"review_status_{state.review_status}",
                )
            if state.approval_status == "AWAITING_APPROVAL":
                return StepArtifact(
                    step_id=step.step_id,
                    step_type="finalize",
                    status="HALTED",
                    confidence=conf,
                    needs_review=True,
                    next_action="awaiting_approval",
                )
            if state.approval_status == "REJECTED":
                return StepArtifact(
                    step_id=step.step_id,
                    step_type="finalize",
                    status="FAILED",
                    confidence=conf,
                    needs_review=True,
                    next_action="rejected",
                )

        state.final_output = state.last_output_text()

        from staff.llm_router.types import ModelSelection, RetrievalBundle

        self.audit.log(
            ctx=ctx,
            selection=ModelSelection(
                capability="reasoning_medium",  # placeholder capability for finalize record
                provider_key="workflow.finalize",
                provider="internal",
                model="finalize",
                lane="",
            ),
            confidence=conf,
            review_status=state.review_status,
            escalation_chain=conf.escalation_reason,
            retrieval=state.retrieval_bundle or RetrievalBundle(),
            source_object_ids=state.source_object_ids,
            workflow_id=state.workflow_id,
            step_id=step.step_id,
            step_type="finalize",
            latency_ms=None,
            cost_estimate=None,
        )

        return StepArtifact(
            step_id=step.step_id,
            step_type="finalize",
            status="DONE",
            output_text=state.final_output,
            confidence=conf,
            needs_review=conf.needs_review,
            citations=state.citations,
            source_object_ids=state.source_object_ids,
        )
