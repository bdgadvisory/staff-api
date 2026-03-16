from __future__ import annotations

from typing import Any

import yaml

from staff.llm_router.types import OutputClass
from staff.workflows.types import WorkflowDefinition, WorkflowStep


def _infer_step_type(raw: dict[str, Any]) -> str:
    # Back-compat with earlier example YAMLs
    if raw.get("action") == "memory_retrieve":
        return "retrieve"

    step = (raw.get("step") or raw.get("id") or "").lower()

    if step in ("retrieve", "retrieval"):
        return "retrieve"
    if step in ("route",):
        return "route"
    if step in ("approval_gate", "human_approval_gate", "human_approval"):
        return "approval_gate"

    if "quill" in step or "rewrite" in step:
        return "rewrite"
    if "voice" in step:
        return "voice_pass"
    if "critique" in step or "editorial" in step:
        return "critique"

    # Default LLM generation step
    return "generate"


def load_workflow(path: str) -> WorkflowDefinition:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    name = data["name"]
    out_class = OutputClass(str(data.get("output_class", "B")))
    dept = data.get("department")

    steps: list[WorkflowStep] = []
    for i, raw in enumerate(data.get("pipeline", [])):
        step_id = raw.get("step") or raw.get("id") or f"step_{i}"
        step_type = raw.get("step_type") or _infer_step_type(raw)
        steps.append(
            WorkflowStep(
                step_id=step_id,
                step_type=step_type,
                capability=raw.get("capability"),
                instruction=raw.get("instruction"),
                required=raw.get("required"),
                when=raw.get("when"),
            )
        )

    return WorkflowDefinition(name=name, output_class=out_class, steps=steps, department=dept)
