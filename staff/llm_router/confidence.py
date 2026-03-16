from __future__ import annotations

from dataclasses import dataclass

from staff.llm_router.types import ConfidenceReport, OutputClass, RiskLevel, TaskContext


@dataclass(frozen=True)
class ConfidencePolicy:
    class_a_review_below: float = 0.70
    class_b_review_below: float = 0.82
    class_c_review_below: float = 0.90


class ConfidenceEngine:
    """Produces structured confidence + review requirement.

    In v1, confidence is heuristic + policy-driven.
    Later: calibrate via benchmarks.
    """

    def __init__(self, policy: ConfidencePolicy):
        self.policy = policy

    def evaluate(
        self,
        ctx: TaskContext,
        output_class: OutputClass,
        risk_level: RiskLevel,
        ambiguity_score: float,
        source_quality: float,
        base_confidence: float,
        escalation_reason: list[str],
    ) -> ConfidenceReport:
        threshold = {
            OutputClass.A: self.policy.class_a_review_below,
            OutputClass.B: self.policy.class_b_review_below,
            OutputClass.C: self.policy.class_c_review_below,
        }[output_class]

        needs_review = base_confidence < threshold or output_class == OutputClass.C

        return ConfidenceReport(
            confidence=base_confidence,
            ambiguity_score=ambiguity_score,
            source_quality=source_quality,
            human_facing=ctx.human_facing,
            needs_review=needs_review,
            risk_level=risk_level,
            escalation_reason=escalation_reason,
            selected_output_class=output_class,
        )
