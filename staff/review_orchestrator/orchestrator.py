from __future__ import annotations

from dataclasses import dataclass

from staff.llm_router.types import LLMResult, ModelSelection, TaskContext
from staff.providers.base import LLMCall, ProviderAdapter


@dataclass(frozen=True)
class ReviewStage:
    name: str
    selection: ModelSelection
    instruction: str


class ReviewOrchestrator:
    """Explicit review orchestration.

    Supports single-pass and chained reviews. Arbitration handled by strong model.
    """

    def __init__(self, adapters: dict[str, ProviderAdapter]):
        self.adapters = adapters

    def run_chain(
        self,
        ctx: TaskContext,
        draft: LLMResult,
        stages: list[ReviewStage],
    ) -> list[LLMResult]:
        results: list[LLMResult] = [draft]

        current_text = draft.text
        for stage in stages:
            adapter = self.adapters[stage.selection.provider]
            call = LLMCall(
                model=stage.selection.model,
                messages=[
                    {"role": "system", "content": stage.instruction},
                    {"role": "user", "content": current_text},
                ],
                temperature=0.2,
                max_tokens=1200,
                metadata={"department": ctx.department, "stage": stage.name},
            )
            out = adapter.complete(call)
            results.append(out)
            current_text = out.text

        return results
