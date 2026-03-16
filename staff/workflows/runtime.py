from __future__ import annotations

import os

import yaml

from staff.audit_logging.logger import AuditLogger
from staff.llm_router.capability_router import CapabilityRouter
from staff.llm_router.confidence import ConfidenceEngine, ConfidencePolicy
from staff.llm_router.escalation import EscalationEngine
from staff.llm_router.prompt_assembly import PromptAssemblyEngine, PromptAssemblyPolicy
from staff.llm_router.retrieval_contract import RetrievalClient
from staff.model_registry.registry import ProviderRegistry
from staff.providers.anthropic_adapter import AnthropicAdapter
from staff.providers.mock_adapter import MockAdapter
from staff.providers.openai_adapter import OpenAIAdapter
from staff.review_orchestrator.orchestrator import ReviewOrchestrator
from staff.workflows.checkpoints import FileCheckpointStore, PostgresCheckpointStore
from staff.workflows.executor import WorkflowExecutor


def build_executor_from_env(*, live_mode: bool | None = None) -> WorkflowExecutor:
    """Build a WorkflowExecutor with adapters chosen by STAFF_LIVE_MODE.

    Default: live_mode is derived from env.
    Tests/harness should pass live_mode=False explicitly.
    """

    if live_mode is None:
        live_mode = os.environ.get("STAFF_LIVE_MODE", "0") == "1"

    registry = ProviderRegistry.from_yaml("staff/model_registry/default_registry.yaml")
    with open("staff/policy/department_policies.yaml", "r", encoding="utf-8") as f:
        dept = yaml.safe_load(f)

    router = CapabilityRouter(registry=registry, department_policies=dept)

    # Retrieval boundary is HTTP/service-side; config is handled inside RetrievalClient.
    retrieval = RetrievalClient()

    if live_mode:
        adapters = {
            "openai": OpenAIAdapter(),
            "anthropic": AnthropicAdapter(),
            # google adapter intentionally not wired in this phase unless explicitly enabled elsewhere
            "google": MockAdapter("google"),
        }
    else:
        adapters = {
            "openai": MockAdapter("openai"),
            "google": MockAdapter("google"),
            "anthropic": MockAdapter("anthropic", behavior={"default_prefix": "[MOCK_REVIEW]"}),
        }

    reviewer = ReviewOrchestrator(adapters=adapters)

    store_kind = os.environ.get("WORKFLOW_CHECKPOINT_STORE")
    if store_kind:
        store_kind = store_kind.lower()
    else:
        # Auto-select: use Postgres only when DB env is configured; otherwise file store (tests/local).
        has_db_env = all(os.environ.get(k) for k in ("INSTANCE_CONNECTION_NAME", "DB_NAME", "DB_USER", "DB_PASSWORD"))
        store_kind = "postgres" if has_db_env else "file"

    checkpoint_store = FileCheckpointStore() if store_kind == "file" else PostgresCheckpointStore()

    return WorkflowExecutor(
        router=router,
        retrieval=retrieval,
        prompt_engine=PromptAssemblyEngine(PromptAssemblyPolicy()),
        adapters=adapters,
        reviewer=reviewer,
        confidence=ConfidenceEngine(ConfidencePolicy()),
        escalation=EscalationEngine(),
        audit=AuditLogger(sink_path=None),
        checkpoint_store=checkpoint_store,
    )
