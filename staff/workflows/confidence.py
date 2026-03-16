from __future__ import annotations

from dataclasses import dataclass

from staff.llm_router.confidence import ConfidenceEngine
from staff.llm_router.types import ConfidenceReport, OutputClass, TaskContext
from staff.workflows.types import WorkflowState


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass(frozen=True)
class StepConfidenceSignals:
    base_confidence: float
    ambiguity_score: float
    source_quality: float
    escalation_reasons: list[str]
    risk_level: str


class StepConfidenceDeriver:
    """Deterministic confidence derivation using available workflow + retrieval signals.

    No randomness. Designed to be calibrated later via benchmarks.
    """

    def __init__(self, engine: ConfidenceEngine):
        self.engine = engine

    def derive(
        self,
        *,
        ctx: TaskContext,
        state: WorkflowState,
        step_type: str,
        review_outcome: str | None = None,
        base_conf_override: float | None = None,
    ) -> ConfidenceReport:
        meta = (state.retrieval_bundle.retrieval_meta if state.retrieval_bundle else {}) or {}
        stale = bool(meta.get("stale_items_present"))
        conflicts = bool(meta.get("conflicts_present"))

        triggers = (state.audit_context.get("classification") or {}).get("triggers", [])
        risk_level = (state.audit_context.get("classification") or {}).get("risk_level", "medium")

        escalation: list[str] = []
        escalation.extend([f"trigger:{t}" for t in triggers])
        if stale:
            escalation.append("stale_items_present")
        if conflicts:
            escalation.append("conflicts_present")

        # Source quality: citations + source_object_ids are required for auditability.
        citations_count = len(state.citations or [])
        source_ids_count = len(state.source_object_ids or [])
        source_quality = 0.4
        if citations_count >= 1 and source_ids_count >= 1:
            source_quality = 0.85
        elif citations_count >= 1 or source_ids_count >= 1:
            source_quality = 0.65

        if stale:
            source_quality -= 0.15
        if conflicts:
            source_quality -= 0.25
        source_quality = _clamp(source_quality)

        # Ambiguity: triggers + conflict/stale flags
        ambiguity = 0.10 + 0.12 * len(triggers)
        if stale:
            ambiguity += 0.15
        if conflicts:
            ambiguity += 0.35
        ambiguity = _clamp(ambiguity)

        # Base confidence by step type (prior to review outcome)
        base_conf = {
            "generate": 0.86,
            "rewrite": 0.84,
            "voice_pass": 0.85,
            "review": 0.82,
            "critique": 0.82,
            "finalize": 0.88,
        }.get(step_type, 0.80)

        # Tighten for OutputClass C
        if state.output_class == OutputClass.C:
            base_conf -= 0.04

        # Penalize weak sources for human-facing
        if ctx.human_facing and source_quality < 0.6:
            base_conf -= 0.12
            escalation.append("weak_sources_for_human_facing")

        # Penalize stale/conflict
        if stale:
            base_conf -= 0.10
        if conflicts:
            base_conf -= 0.18

        # Review outcome overrides
        if review_outcome:
            if review_outcome in ("PASS",):
                base_conf = max(base_conf, 0.90)
            elif review_outcome in ("PASS_WITH_WARNINGS",):
                base_conf = max(base_conf, 0.84)
                escalation.append("review_warnings")
            elif review_outcome == "REWRITE_REQUIRED":
                base_conf = min(base_conf, 0.40)
                escalation.append("rewrite_required")
            elif review_outcome == "ESCALATE_TO_HUMAN":
                base_conf = min(base_conf, 0.25)
                escalation.append("escalate_to_human")

        if base_conf_override is not None:
            base_conf = base_conf_override

        base_conf = _clamp(base_conf)

        # Finalize aggregation rule: must not fabricate strong confidence.
        if step_type == "finalize":
            # Aggregate from prior step confidences if present.
            prior = [a.confidence.confidence for a in state.step_artifacts if a.confidence is not None]
            if prior:
                base_conf = min(base_conf, min(prior))
            if state.output_class == OutputClass.C:
                if state.review_status in ("REWRITE_REQUIRED", "ESCALATE_TO_HUMAN", "NOT_REVIEWED"):
                    base_conf = min(base_conf, 0.35)
                    escalation.append(f"finalize_blocked_by_review_status:{state.review_status}")
                if state.approval_status == "AWAITING_APPROVAL":
                    base_conf = min(base_conf, 0.30)
                    escalation.append("pending_approval")
                if state.approval_status == "REJECTED":
                    base_conf = min(base_conf, 0.10)
                    escalation.append("rejected")

        # Use the shared ConfidenceEngine thresholds to determine needs_review.
        return self.engine.evaluate(
            ctx,
            output_class=state.output_class,
            risk_level=risk_level,
            ambiguity_score=ambiguity,
            source_quality=source_quality,
            base_confidence=base_conf,
            escalation_reason=escalation,
        )
