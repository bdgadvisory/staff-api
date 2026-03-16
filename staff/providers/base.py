from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from staff.llm_router.types import LLMResult


@dataclass(frozen=True)
class LLMCall:
    model: str
    messages: list[dict[str, str]]
    temperature: float = 0.2
    max_tokens: int = 800
    metadata: dict[str, Any] | None = None


class ProviderAdapter(ABC):
    name: str

    @abstractmethod
    def complete(self, call: LLMCall) -> LLMResult:
        raise NotImplementedError
