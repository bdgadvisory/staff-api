#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

python3 - <<'PY'
from pathlib import Path
import re

p = Path("cloudbuild.yaml")
s = p.read_text(encoding="utf-8")

# 1) Replace hard-coded registry hostname with ${_REGION}-docker.pkg.dev
s2 = s.replace("us-central1-docker.pkg.dev", "${_REGION}-docker.pkg.dev")

# 2) Add --revision-suffix $SHORT_SHA to the gcloud run deploy args if not present
if "--revision-suffix" not in s2:
    # Insert right before the closing ] of the deploy args block
    # Look for the deploy args list end after --no-allow-unauthenticated
    s2 = re.sub(
        r'("--no-allow-unauthenticated"\s*\]\s*)',
        '"--no-allow-unauthenticated",\n "--revision-suffix","$SHORT_SHA"\n ]',
        s2,
        count=1,
        flags=re.M
    )

if s2 == s:
    print("No changes needed.")
else:
    p.write_text(s2, encoding="utf-8")
    print("Patched cloudbuild.yaml")
PY

git add cloudbuild.yaml
git commit -m "Harden Cloud Build deploy (regionized registry + revision suffix)" || true
git push public main
