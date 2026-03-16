from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from staff.audit_logging.logger import AuditLogger
from staff.llm_router.capability_router import CapabilityRouter, RoutePlan
from staff.llm_router.confidence import ConfidenceEngine
from staff.llm_router.escalation import EscalationEngine
from staff.llm_router.prompt_assembly import PromptAssemblyEngine
from staff.llm_router.retrieval_contract import RetrievalClient, RetrievalRequest
from staff.llm_router.task_classifier import TaskClassifier
from staff.llm_router.types import LLMResult, ModelSelection, PromptAssembly, RetrievalBundle, TaskContext
from staff.providers.base import LLMCall, ProviderAdapter
from staff.review_orchestrator.orchestrator import ReviewOrchestrator, ReviewStage


@dataclass(frozen=True)
class TaskResult:
    route: RoutePlan
    retrieval: RetrievalBundle
    prompt: PromptAssembly
    primary_result: LLMResult
    review_results: list[LLMResult]
    confidence: Any
    escalation: Any


class WorkflowRunner:
    """Executes declarative pipelines (examples/workflows/*.yaml).

    v1 goal: wire the *structure* so later we can make each step more sophisticated
    without changing orchestration contract.
    """

    def __init__(
        self,
        registry_router: CapabilityRouter,
        retrieval: RetrievalClient,
        prompt_engine: PromptAssemblyEngine,
        adapters: dict[str, ProviderAdapter],
        reviewer: ReviewOrchestrator,
        confidence: ConfidenceEngine,
        escalation: EscalationEngine,
        audit: AuditLogger,
        classifier: TaskClassifier | None = None,
    ):
        self.router = registry_router
        self.retrieval = retrieval
        self.prompt_engine = prompt_engine
        self.adapters = adapters
        self.reviewer = reviewer
        self.confidence = confidence
        self.escalation = escalation
        self.audit = audit
        self.classifier = classifier or TaskClassifier()

    def load_workflow(self, path: str) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def run_task(self, ctx: TaskContext, user_input: str, workflow: dict[str, Any]) -> TaskResult:
        # 1) classify
        cls = self.classifier.classify(ctx, user_input)

        # 2) route (department policy + registry)
        plan = self.router.route(ctx, intent={"output_class": cls.output_class.value, "triggers": cls.triggers})

        # 3) retrieval (governed contract)
        req = RetrievalRequest(
            query=user_input,
            actor=ctx.actor,
            scope=ctx.scope,
            privacy_class=ctx.privacy_class,
            department=ctx.department,
            task_type=ctx.task_type,
        )
        bundle = self.retrieval.retrieve(ctx, req)

        # 4) prompt assembly
        prompt = self.prompt_engine.assemble(ctx, user_input=user_input, bundle=bundle)

        # 5) primary completion
        primary = self._complete(ctx, plan.primary, prompt)

        # 6) confidence + escalation
        # v1 heuristics: base_confidence derived from output class and retrieval quality
        source_quality = min(1.0, (len(bundle.semantic_chunks) / 6.0) if bundle.semantic_chunks else 0.4)
        ambiguity_score = 0.2 if cls.triggers else 0.1
        base_conf = 0.92 if plan.output_class.value == "C" else 0.85
        escalation_decision = self.escalation.decide(ctx, plan.output_class, cls.risk_level, cls.triggers)
        conf = self.confidence.evaluate(
            ctx,
            output_class=plan.output_class,
            risk_level=cls.risk_level,
            ambiguity_score=ambiguity_score,
            source_quality=source_quality,
            base_confidence=base_conf,
            escalation_reason=escalation_decision.reasons,
        )

        # 7) review orchestration
        review_results: list[LLMResult] = []
        if conf.needs_review and plan.reviewers:
            stages = [
                ReviewStage(
                    name=f"review_{i}",
                    selection=sel,
                    instruction=(
                        "You are a critical reviewer. Identify weaknesses, missing constraints, tone risks, and "
                        "required rewrites. If the draft is acceptable, say PASS and provide minor edits only."
                    ),
                )
                for i, sel in enumerate(plan.reviewers)
            ]
            review_results = self.reviewer.run_chain(ctx, draft=primary, stages=stages)[1:]

        # 8) audit
        self.audit.log(
            ctx=ctx,
            selection=plan.primary,
            confidence=conf,
            review_status="REVIEWED" if review_results else "NOT_REVIEWED",
            escalation_chain=escalation_decision.reasons,
            retrieval=bundle,
            source_object_ids=prompt.included_object_ids,
            latency_ms=primary.latency_ms,
            cost_estimate=primary.cost_estimate,
        )

        return TaskResult(
            route=plan,
            retrieval=bundle,
            prompt=prompt,
            primary_result=primary,
            review_results=review_results,
            confidence=conf,
            escalation=escalation_decision,
        )

    def _complete(self, ctx: TaskContext, selection: ModelSelection, prompt: PromptAssembly) -> LLMResult:
        adapter = self.adapters.get(selection.provider)
        if not adapter:
            raise RuntimeError(f"No adapter registered for provider={selection.provider}")

        call = LLMCall(
            model=selection.model,
            messages=prompt.messages,
            temperature=0.2,
            max_tokens=min(2000, prompt.token_budget // 3),
            metadata={"request_id": ctx.request_id, "department": ctx.department, "task_type": ctx.task_type},
        )
        return adapter.complete(call)
