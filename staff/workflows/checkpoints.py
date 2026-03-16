from __future__ import annotations

import json
import os
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path
from typing import Any

from staff.workflows.types import StepArtifact, WorkflowState


class WorkflowCheckpointStore(ABC):
    @abstractmethod
    def save_pre_call(self, workflow_id: str, state: WorkflowState, step_id: str, call_spec: dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def save_post_call(self, workflow_id: str, state: WorkflowState, step_id: str, artifact: StepArtifact) -> str:
        raise NotImplementedError

    @abstractmethod
    def load(self, workflow_id: str) -> dict[str, Any] | None:
        raise NotImplementedError


class FileCheckpointStore(WorkflowCheckpointStore):
    """Durable JSON checkpoints on disk.

    Layout:
      <dir>/<workflow_id>.json

    NOTE: This stores the *workflow state* needed for resume. It is not meant to be a full audit log.
    """

    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or os.environ.get("WORKFLOW_CHECKPOINT_DIR", "./.workflow_checkpoints")
        Path(self.base_dir).mkdir(parents=True, exist_ok=True)

    def _path(self, workflow_id: str) -> Path:
        return Path(self.base_dir) / f"{workflow_id}.json"

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp_path, path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
        return str(path)

    def _serialize_state(self, state: WorkflowState) -> dict[str, Any]:
        # Minimal stable JSON form (dataclasses + nested artifacts)
        return {
            "workflow_id": state.workflow_id,
            "workflow_type": state.workflow_type,
            "department": state.department,
            "task_type": state.task_type,
            "output_class": state.output_class.value,
            "current_step_index": state.current_step,
            "input_payload": state.input_payload,
            "completed_artifacts": [asdict(a) for a in state.step_artifacts],
            "retry_state": state.retry_state,
            "next_resume_at": state.next_resume_at,
            "workflow_call_counts": state.workflow_call_counts,
            "review_pass_count": state.review_pass_count,
            "halted": state.halted,
            "halt_reason": state.halt_reason,
            "checkpoint": state.checkpoint,
            "audit_context": state.audit_context,
            "updated_at": time.time(),
        }

    def save_pre_call(self, workflow_id: str, state: WorkflowState, step_id: str, call_spec: dict[str, Any]) -> str:
        payload = self._serialize_state(state)
        payload["checkpoint_stage"] = "pre_call"
        payload["current_step_id"] = step_id
        payload["call_spec"] = call_spec
        out_path = self._path(workflow_id)
        path = self._atomic_write_json(out_path, payload)
        state.checkpoint["checkpoint_path"] = path
        return path

    def save_post_call(self, workflow_id: str, state: WorkflowState, step_id: str, artifact: StepArtifact) -> str:
        payload = self._serialize_state(state)
        payload["checkpoint_stage"] = "post_call"
        payload["current_step_id"] = step_id
        payload["last_artifact"] = asdict(artifact)
        out_path = self._path(workflow_id)
        path = self._atomic_write_json(out_path, payload)
        state.checkpoint["checkpoint_path"] = path
        return path

    def load(self, workflow_id: str) -> dict[str, Any] | None:
        p = self._path(workflow_id)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_checkpoints(self) -> list[Path]:
        return sorted(Path(self.base_dir).glob("*.json"))
