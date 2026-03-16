#!/usr/bin/env bash
set -euo pipefail

pytest -q tests/test_workflow_executor.py
