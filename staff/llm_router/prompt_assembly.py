from __future__ import annotations

from dataclasses import dataclass

from staff.llm_router.types import PromptAssembly, RetrievalBundle, TaskContext


@dataclass(frozen=True)
class PromptAssemblyPolicy:
    token_budget: int = 6000
    # caps (mirror spec defaults)
    max_graph_facts: int = 20
    max_semantic_chunks: int = 6
    max_episodic_events: int = 12


class PromptAssemblyEngine:
    """Turns governed retrieval bundles into model-ready prompts.

    Required behaviors:
    - privacy filtering BEFORE prompt construction (done upstream in retrieval)
    - trust-aware prioritization
    - stale/conflict handling surfaced via constraints
    - token-budget shaping
    - citation retention for auditability
    """

    def __init__(self, policy: PromptAssemblyPolicy):
        self.policy = policy

    def assemble(self, ctx: TaskContext, user_input: str, bundle: RetrievalBundle) -> PromptAssembly:
        notes: list[str] = []

        # Priority order (minimum baseline)
        graph = bundle.graph_facts[: self.policy.max_graph_facts]
        constraints = bundle.constraints
        semantic = bundle.semantic_chunks[: self.policy.max_semantic_chunks]
        episodic = bundle.episodic_events[: self.policy.max_episodic_events]

        included_ids: list[str] = []
        for ch in semantic:
            doc_id = ch.get("doc_id") or ch.get("id")
            if doc_id:
                included_ids.append(str(doc_id))

        system = (
            "You are Staff. Follow constraints strictly. "
            "Do not reveal private memory. Use citations internally for auditability."
        )

        memory_block = {
            "graph_facts": graph,
            "constraints": constraints,
            "semantic_chunks": semantic,
            "episodic_events": episodic,
            "citations": bundle.citations,
        }

        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"TaskContext: department={ctx.department} task_type={ctx.task_type} "
                    f"human_facing={ctx.human_facing} privacy_class={ctx.privacy_class} scope={ctx.scope}\n\n"
                    f"RetrievedMemory(JSON): {memory_block}\n\n"
                    f"UserInput: {user_input}"
                ),
            },
        ]

        return PromptAssembly(
            system=system,
            messages=messages,
            token_budget=self.policy.token_budget,
            included_object_ids=included_ids,
            notes=notes,
        )
