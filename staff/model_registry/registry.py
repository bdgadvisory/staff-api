from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import json

import yaml

from staff.llm_router.types import Capability, ModelSelection


@dataclass(frozen=True)
class RegistryModel:
    provider: str
    model: str
    lane: str


class ProviderRegistry:
    """The only place model names are allowed to live.

    Workflow/routing code selects CAPABILITIES. The registry resolves those into provider/model.
    """

    def __init__(self, data: dict[str, Any]):
        self._data = data

    @classmethod
    def from_json(cls, path: str) -> "ProviderRegistry":
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    @classmethod
    def from_yaml(cls, path: str) -> "ProviderRegistry":
        with open(path, "r", encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    def resolve(self, capability: Capability) -> ModelSelection:
        mapping = self._data["capability_map"][capability]
        provider_key = mapping["provider_key"]
        model_entry = self._data["providers"][provider_key]
        return ModelSelection(
            capability=capability,
            provider_key=provider_key,
            provider=model_entry["provider"],
            model=model_entry["model"],
            lane=model_entry.get("lane", "")
        )
