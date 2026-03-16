from __future__ import annotations

from dataclasses import dataclass

from staff.llm_router.types import OutputClass, RiskLevel, TaskContext


IMMEDIATE_ESCALATION_TRIGGERS = {
    "emotional_sensitivity_detected",
    "health_related",
    "public_publication",
    "provider_disagreement",
    "source_conflict",
    "permission_change",
    "architecture_change",
    "production_code_change",
}


@dataclass(frozen=True)
class EscalationDecision:
    escalate: bool
    reasons: list[str]


class EscalationEngine:
    def decide(
        self,
        ctx: TaskContext,
        output_class: OutputClass,
        risk_level: RiskLevel,
        triggers: list[str],
    ) -> EscalationDecision:
        reasons: list[str] = []

        if output_class == OutputClass.C:
            reasons.append("class_c_requires_review")

        if risk_level in ("high", "critical"):
            reasons.append(f"risk_level_{risk_level}")

        for t in triggers:
            if t in IMMEDIATE_ESCALATION_TRIGGERS:
                reasons.append(t)

        return EscalationDecision(escalate=len(reasons) > 0, reasons=reasons)
