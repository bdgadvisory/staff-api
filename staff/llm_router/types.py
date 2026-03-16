from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Sequence


# --- Core enums (capability-based; no model names here) ---

Capability = Literal[
    # reasoning
    "reasoning_low",
    "reasoning_medium",
    "reasoning_high",
    "reasoning_critical",
    # coding
    "coding_basic",
    "coding_multi_file",
    "coding_agentic",
    "coding_architecture",
    # research
    "research_fast",
    "research_grounded_web",
    "research_synthesis",
    "research_conflict_resolution",
    # writing
    "writing_draft",
    "writing_rewrite",
    "writing_voice_alignment",
    "writing_editorial_review",
    "writing_publication_ready",
    # operational
    "classification_fast",
    "summarization_bulk",
    "memory_tagging",
    "qa_bulk_validation",
    "qa_critique",
    "qa_arbitration",
]


class OutputClass(str, Enum):
    A = "A"  # low-risk internal
    B = "B"  # human-facing but reversible
    C = "C"  # trust-critical / public / prod-impacting


RiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class TaskContext:
    request_id: str
    department: str  # nestor | linkedin | foundry | workbench | qa | staff
    task_type: str
    actor: dict[str, Any]  # {actor_type, actor_id}
    human_facing: bool
    privacy_class: str  # per staff-memory taxonomy
    scope: str


@dataclass(frozen=True)
class RetrievalBundle:
    """Governed retrieval contract payload.

    IMPORTANT: This object must be produced by the retrieval layer after privacy/trust filtering,
    not by ad-hoc file reads.
    """

    graph_facts: list[dict[str, Any]] = field(default_factory=list)
    semantic_chunks: list[dict[str, Any]] = field(default_factory=list)
    episodic_events: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PromptAssembly:
    system: str
    messages: list[dict[str, str]]  # OpenAI-style {role, content}
    token_budget: int
    included_object_ids: list[str]
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConfidenceReport:
    confidence: float  # 0..1
    ambiguity_score: float
    source_quality: float
    human_facing: bool
    needs_review: bool
    risk_level: RiskLevel
    escalation_reason: list[str]
    selected_output_class: OutputClass


@dataclass(frozen=True)
class ModelSelection:
    capability: Capability
    provider_key: str  # registry key (e.g. openai.default_reasoning)
    provider: str  # openai | google | anthropic
    model: str  # exact model id/version (registry-owned)
    lane: str  # strong | cheap | review | editor | etc.


@dataclass
class LLMResult:
    text: str
    raw: Any
    provider: str
    model: str
    latency_ms: int | None = None
    cost_estimate: float | None = None
