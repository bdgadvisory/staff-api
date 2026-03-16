from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    category: str
    input: dict[str, Any]
    expected: dict[str, Any] | None = None


@dataclass(frozen=True)
class BenchmarkResult:
    case_id: str
    model: str
    provider: str
    score: float
    notes: list[str]


class BenchmarkHarness:
    """Benchmark harness.

    v1: supports loading suite definitions and producing a structured result list.
    Scoring is still a stub; implement per-category rubrics and/or LLM-judge with calibration.
    """

    def load_suite(self, path: str) -> list[BenchmarkCase]:
        import yaml

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        cases: list[BenchmarkCase] = []
        for c in data.get("cases", []):
            cases.append(
                BenchmarkCase(
                    id=c["id"],
                    category=c["category"],
                    input=c.get("input", {}),
                    expected=c.get("expected"),
                )
            )
        return cases

    def run_suite(self, suite: list[BenchmarkCase]) -> list[BenchmarkResult]:
        # Placeholder runner: returns 0.0 scores until provider execution + rubric scoring is implemented.
        results: list[BenchmarkResult] = []
        for case in suite:
            results.append(
                BenchmarkResult(
                    case_id=case.id,
                    model="UNRUN",
                    provider="UNRUN",
                    score=0.0,
                    notes=[
                        "Runner not implemented: wire to WorkflowRunner + adapters.",
                        f"category={case.category}",
                    ],
                )
            )
        return results
