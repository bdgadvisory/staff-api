from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import yaml

from staff.audit_logging.logger import AuditLogger
from staff.llm_router.capability_router import CapabilityRouter
from staff.llm_router.confidence import ConfidenceEngine, ConfidencePolicy
from staff.llm_router.escalation import EscalationEngine
from staff.llm_router.prompt_assembly import PromptAssemblyEngine, PromptAssemblyPolicy
from staff.llm_router.retrieval_contract import RetrievalClient
from staff.model_registry.registry import ProviderRegistry
from staff.providers.mock_adapter import MockAdapter
from staff.review_orchestrator.orchestrator import ReviewOrchestrator
from staff.workflows.executor import WorkflowExecutor


def _stub_retrieve_response(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    base = {
        "graph_facts": [],
        "semantic_chunks": [
            {
                "doc_id": "qmd/policy/cheap-gather-strong-speak",
                "type": "policy",
                "trust_level": "system_verified",
                "privacy_class": "internal",
                "review_after": "2099-01-01",
                "text": "Cheap models may gather. Strong models must speak for Class C outputs.",
            }
        ],
        "episodic_events": [],
        "constraints": [],
        "citations": [{"object_id": "qmd/policy/cheap-gather-strong-speak"}],
        "retrieval_meta": {
            "stale_items_present": False,
            "conflicts_present": False,
            "privacy_filters_applied": [],
            "trust_filters_applied": [],
            "source_object_ids": ["qmd/policy/cheap-gather-strong-speak"],
        },
    }
    if overrides:
        # shallow merge is enough for tests
        base.update(overrides)
        if "retrieval_meta" in overrides:
            base["retrieval_meta"].update(overrides["retrieval_meta"])
    return base


@pytest.fixture
def http_retrieval_client() -> RetrievalClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/retrieve"
        payload = json.loads(request.content.decode("utf-8"))
        # minimal contract assertions
        for k in (
            "agent_id",
            "department",
            "task_type",
            "query",
            "scope",
            "subject_ids",
            "output_class",
        ):
            assert k in payload

        body = _stub_retrieve_response()
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="http://stub")
    return RetrievalClient(base_url="http://stub", mode="http", http_client=client)


@pytest.fixture
def router() -> CapabilityRouter:
    registry = ProviderRegistry.from_yaml("staff/model_registry/default_registry.yaml")
    with open("staff/policy/department_policies.yaml", "r", encoding="utf-8") as f:
        dept = yaml.safe_load(f)
    return CapabilityRouter(registry=registry, department_policies=dept)


@pytest.fixture
def executor(router: CapabilityRouter, http_retrieval_client: RetrievalClient) -> WorkflowExecutor:
    adapters = {
        "openai": MockAdapter("openai"),
        "google": MockAdapter("google"),
        "anthropic": MockAdapter(
            "anthropic",
            behavior={
                "default_prefix": "[MOCK_REVIEW]",
                "qa_status_by_step_id": {
                    "critique": "PASS_WITH_WARNINGS",
                    "arbitration": "PASS",
                    "editorial_critique": "PASS_WITH_WARNINGS",
                    "review": "PASS",
                },
            },
        ),
    }
    reviewer = ReviewOrchestrator(adapters=adapters)
    return WorkflowExecutor(
        router=router,
        retrieval=http_retrieval_client,
        prompt_engine=PromptAssemblyEngine(PromptAssemblyPolicy()),
        adapters=adapters,
        reviewer=reviewer,
        confidence=ConfidenceEngine(ConfidencePolicy()),
        escalation=EscalationEngine(),
        audit=AuditLogger(sink_path=None),
    )
