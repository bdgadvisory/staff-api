from pathlib import Path
import yaml

def critic(design_path: str) -> None:
    d = yaml.safe_load(Path(design_path).read_text(encoding="utf-8"))
    issues = []

    mp = d.get("model_policy") or {}
    if not mp.get("default"):
        issues.append("model_policy.default is missing")
    if not mp.get("escalated"):
        issues.append("model_policy.escalated is missing")
    if not (d.get("departments") or {}):
        issues.append("no departments defined")

    connectors = d.get("connectors") or {}
    wa = connectors.get("whatsapp")
    if wa and wa.get("approval_required_for_send") is not True:
        issues.append("connectors.whatsapp.approval_required_for_send should be true for safety")

    if issues:
        print("[critic] FAIL")
        for i in issues:
            print(" -", i)
        raise SystemExit(2)

    print("[critic] OK")
