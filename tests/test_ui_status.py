import json
import os
import time

import pytest


def _write_checkpoint(dir_path, workflow_id: str, payload: dict):
    p = dir_path / f"{workflow_id}.json"
    p.write_text(json.dumps(payload))
    return p


def test_ui_status_no_checkpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_CHECKPOINT_DIR", str(tmp_path))
    from main import ui_status

    out = ui_status()
    assert out["ok"] is True
    assert out["workflow_resume"]["halted_count"] == 0
    assert out["workflow_resume"]["items"] == []


def test_ui_status_one_auto_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_CHECKPOINT_DIR", str(tmp_path))

    now = time.time()
    _write_checkpoint(
        tmp_path,
        "wf-1",
        {
            "workflow_id": "wf-1",
            "workflow_type": "x",
            "department": "scribe",
            "task_type": "t",
            "output_class": "B",
            "current_step_index": 2,
            "current_step_id": "gen",
            "completed_artifacts": [],
            "retry_state": {"retry_count_by_step": {"gen": 1}, "last_error": "e", "provider_name": "openai", "model_name": "gpt"},
            "halted": True,
            "halt_reason": "provider_rate_limit",
            "next_resume_at": now + 30,
            "checkpoint": {"checkpoint_path": str(tmp_path / "wf-1.json")},
            "last_artifact": {"next_action": "auto_resume_scheduled"},
        },
    )

    from main import ui_status

    out = ui_status()
    assert out["workflow_resume"]["halted_count"] == 1
    assert out["services"]["workflow_resume_tick"]["status"] == "ok"


def test_ui_status_overdue_degraded(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_CHECKPOINT_DIR", str(tmp_path))

    now = time.time()
    _write_checkpoint(
        tmp_path,
        "wf-2",
        {
            "workflow_id": "wf-2",
            "workflow_type": "x",
            "department": "scribe",
            "task_type": "t",
            "output_class": "B",
            "current_step_index": 2,
            "current_step_id": "gen",
            "completed_artifacts": [],
            "retry_state": {"retry_count_by_step": {"gen": 1}, "last_error": "e", "provider_name": "openai", "model_name": "gpt"},
            "halted": True,
            "halt_reason": "provider_rate_limit",
            "next_resume_at": now - 999,
            "checkpoint": {"checkpoint_path": str(tmp_path / "wf-2.json")},
            "last_artifact": {"next_action": "auto_resume_scheduled"},
        },
    )

    from main import ui_status

    out = ui_status()
    assert out["services"]["workflow_resume_tick"]["status"] == "degraded"


def test_ui_status_manual_intervention_count(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_CHECKPOINT_DIR", str(tmp_path))

    _write_checkpoint(
        tmp_path,
        "wf-3",
        {
            "workflow_id": "wf-3",
            "workflow_type": "x",
            "department": "scribe",
            "task_type": "t",
            "output_class": "B",
            "current_step_index": 2,
            "current_step_id": "gen",
            "completed_artifacts": [],
            "retry_state": {"retry_count_by_step": {"gen": 7}, "last_error": "e", "provider_name": "openai", "model_name": "gpt"},
            "halted": True,
            "halt_reason": "provider_retry_budget_exhausted",
            "next_resume_at": None,
            "checkpoint": {"checkpoint_path": str(tmp_path / "wf-3.json")},
            "last_artifact": {"next_action": "manual_intervention_required"},
        },
    )

    from main import ui_status

    out = ui_status()
    assert out["workflow_resume"]["manual_intervention_required_count"] == 1


def test_ui_status_invalid_checkpoint_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_CHECKPOINT_DIR", str(tmp_path))

    # invalid JSON
    (tmp_path / "bad.json").write_text("{not json")

    from main import ui_status

    out = ui_status()
    assert out["ok"] is True
    assert out["workflow_resume"].get("invalid_checkpoint_count", 0) >= 1
