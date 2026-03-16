from __future__ import annotations

from dataclasses import dataclass

from staff.llm_router.types import OutputClass, RiskLevel, TaskContext


@dataclass(frozen=True)
class Classification:
    output_class: OutputClass
    risk_level: RiskLevel
    triggers: list[str]


class TaskClassifier:
    """Heuristic v1 classifier.

    This is intentionally conservative. Benchmarks should later calibrate it.

    Produces:
    - output class A/B/C suggestion
    - risk level
    - escalation triggers (used by EscalationEngine)
    """

    HEALTH_WORDS = {"symptom", "diagnosis", "doctor", "medicine", "hospital", "pain"}
    EMOTION_WORDS = {"upset", "angry", "sad", "anxious", "hurt", "argument", "fight"}
    PUBLIC_WORDS = {"linkedin", "twitter", "post", "publish", "press", "public"}
    PROD_WORDS = {"production", "deploy", "migration", "schema", "incident", "rollback"}

    def classify(self, ctx: TaskContext, text: str) -> Classification:
        t = (text or "").lower()
        triggers: list[str] = []

        def has_any(words: set[str]) -> bool:
            return any(w in t for w in words)

        if has_any(self.HEALTH_WORDS):
            triggers.append("health_related")
        if has_any(self.EMOTION_WORDS) and ctx.department == "nestor":
            triggers.append("emotional_sensitivity_detected")
        if has_any(self.PUBLIC_WORDS) or ctx.department == "scribe":
            triggers.append("public_publication")
        if has_any(self.PROD_WORDS) or ctx.task_type in ("code_change", "deploy", "migration"):
            triggers.append("production_code_change")

        # Default output class by context
        if ctx.department in ("scribe", "nestor", "foundry"): 
            output_class = OutputClass.C
        elif ctx.human_facing:
            output_class = OutputClass.B
        else:
            output_class = OutputClass.A

        # Risk
        if "public_publication" in triggers or "health_related" in triggers:
            risk: RiskLevel = "critical"
        elif "emotional_sensitivity_detected" in triggers or "production_code_change" in triggers:
            risk = "high"
        else:
            risk = "medium" if output_class != OutputClass.A else "low"

        # Hard bump: any immediate trigger => Class C
        if triggers and output_class != OutputClass.C:
            output_class = OutputClass.C

        return Classification(output_class=output_class, risk_level=risk, triggers=triggers)
