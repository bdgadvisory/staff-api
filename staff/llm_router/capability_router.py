from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from staff.llm_router.types import Capability, ModelSelection, OutputClass, RiskLevel, TaskContext
from staff.model_registry.registry import ProviderRegistry


@dataclass(frozen=True)
class RoutePlan:
    output_class: OutputClass
    risk_level: RiskLevel
    selected_capabilities: list[Capability]
    primary: ModelSelection
    reviewers: list[ModelSelection]
    notes: list[str]


class CapabilityRouter:
    """Capability-first router.

    - Selects output class (A/B/C)
    - Selects required capabilities
    - Resolves to provider/model via ProviderRegistry
    - Adds reviewer chain per department policy

    NOTE: classification of risk/sensitivity is policy-driven; wire a classifier in v1.
    """

    def __init__(self, registry: ProviderRegistry, department_policies: dict[str, Any]):
        self.registry = registry
        self.department_policies = department_policies

    def route(self, ctx: TaskContext, intent: dict[str, Any]) -> RoutePlan:
        dept = ctx.department
        pol = self.department_policies.get(dept, {})

        output_class = OutputClass(pol.get("default_output_class", "B"))
        risk_level: RiskLevel = pol.get("default_risk_level", "medium")

        # Hard rule: cheap models may gather; strong models must speak for trust-critical outputs.
        if output_class == OutputClass.C:
            primary_cap: Capability = pol.get("class_c_primary_capability", "reasoning_high")
        else:
            primary_cap = pol.get("default_primary_capability", "reasoning_medium")

        selected_caps: list[Capability] = [primary_cap]

        primary = self.registry.resolve(primary_cap)

        reviewers: list[ModelSelection] = []
        for cap in pol.get("review_chain_capabilities", []):
            reviewers.append(self.registry.resolve(cap))

        return RoutePlan(
            output_class=output_class,
            risk_level=risk_level,
            selected_capabilities=selected_caps,
            primary=primary,
            reviewers=reviewers,
            notes=[],
        )
