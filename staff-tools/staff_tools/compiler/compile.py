import json
from pathlib import Path
import yaml

def compile_design(design_path: str, out_dir: str) -> None:
    dpath = Path(design_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    design = yaml.safe_load(dpath.read_text(encoding="utf-8"))

    # routing.json: minimal routing table (dept -> task -> policy)
    routing = {"version": design.get("version", 0), "departments": {}}
    for dept, dept_spec in (design.get("departments") or {}).items():
        routing["departments"][dept] = {}
        for task, task_spec in (dept_spec.get("tasks") or {}).items():
            routing["departments"][dept][task] = {
                "approval_required": bool(task_spec.get("approval_required", True)),
                "outputs": task_spec.get("outputs", []),
            }

    # policies.json: model policy + connector policies
    policies = {
        "model_policy": design.get("model_policy", {}),
        "connectors": design.get("connectors", {}),
    }

    (out / "routing.json").write_text(json.dumps(routing, indent=2), encoding="utf-8")
    (out / "policies.json").write_text(json.dumps(policies, indent=2), encoding="utf-8")

    print(f"[compile] wrote {out/'routing.json'}")
    print(f"[compile] wrote {out/'policies.json'}")
