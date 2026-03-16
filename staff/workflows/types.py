from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from staff.llm_router.types import ConfidenceReport, ModelSelection, OutputClass, RetrievalBundle

StepType = Literal[
    "classify",
    "retrieve",
    "route",
    "generate",
    "rewrite",
    "review",
    "critique",
    "voice_pass",
    "approval_gate",
    "audit",
    "finalize",
]

StepStatus = Literal["PENDING", "RUNNING", "DONE", "HALTED", "FAILED", "SKIPPED"]

ReviewStatus = Literal["NOT_REVIEWED", "REVIEWED", "REWRITE_REQUIRED", "ESCALATE_TO_HUMAN"]
ApprovalStatus = Literal["NOT_REQUIRED", "AWAITING_APPROVAL", "APPROVED", "REJECTED"]


@dataclass
class StepArtifact:
    step_id: str
    step_type: StepType
    status: StepStatus

    selected_capability: str | None = None
    selected_provider: str | None = None
    selected_model: str | None = None

    input_refs: list[str] = field(default_factory=list)

    output_text: str | None = None
    output_structured: dict[str, Any] | None = None

    confidence: ConfidenceReport | None = None
    needs_review: bool | None = None

    citations: list[dict[str, Any]] = field(default_factory=list)
    source_object_ids: list[str] = field(default_factory=list)

    # Resumption / retry metadata (populated on HALTED/FAILED provider conditions)
    retry_count: int | None = None
    halt_reason: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    backoff_s: float | None = None
    auto_resume_scheduled: bool | None = None
    resumed_from_checkpoint: bool | None = None
    cooldown_state: dict[str, Any] | None = None

    next_action: str | None = None


@dataclass
class WorkflowState:
    workflow_id: str
    workflow_type: str
    department: str
    task_type: str
    output_class: OutputClass

    current_step: int = 0
    input_payload: dict[str, Any] = field(default_factory=dict)

    retrieval_bundle: RetrievalBundle | None = None

    step_artifacts: list[StepArtifact] = field(default_factory=list)

    citations: list[dict[str, Any]] = field(default_factory=list)
    source_object_ids: list[str] = field(default_factory=list)

    review_status: ReviewStatus = "NOT_REVIEWED"
    approval_status: ApprovalStatus = "NOT_REQUIRED"

    final_output: str | None = None

    audit_context: dict[str, Any] = field(default_factory=dict)

    # Resumption without re-running prior steps
    halted: bool = False
    halt_reason: str | None = None
    next_resume_at: float | None = None

    retry_state: dict[str, Any] = field(
        default_factory=lambda: {
            "retry_count_by_step": {},
            "last_error": None,
            "provider_name": None,
            "model_name": None,
        }
    )

    checkpoint: dict[str, Any] = field(
        default_factory=lambda: {
            "last_completed_step_index": None,
            "last_completed_step_id": None,
            "checkpoint_path": None,
        }
    )

    workflow_call_counts: dict[str, Any] = field(default_factory=lambda: {"total": 0, "by_provider": {}, "by_model": {}})
    review_pass_count: int = 0

    def last_output_text(self) -> str | None:
        for a in reversed(self.step_artifacts):
            if a.output_text:
                return a.output_text
        return None

    def artifact_for_step(self, step_id: str) -> StepArtifact | None:
        for a in self.step_artifacts:
            if a.step_id == step_id:
                return a
        return None

    def set_sources_from_bundle(self) -> None:
        if not self.retrieval_bundle:
            return
        meta = self.retrieval_bundle.retrieval_meta or {}
        self.citations = self.retrieval_bundle.citations or []
        self.source_object_ids = list(dict.fromkeys(meta.get("source_object_ids", []) or []))


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    step_type: StepType

    # capability-based selection for LLM steps
    capability: str | None = None

    # optional templated instructions
    instruction: str | None = None

    # gate config
    required: bool | None = None

    when: str | None = None  # e.g. confidence_below_threshold


@dataclass
class WorkflowDefinition:
    name: str
    output_class: OutputClass
    steps: list[WorkflowStep]
    department: str | None = None  # metadata (capability domain), e.g. scribe
