-- Workflow runtime durability: checkpoints + run status

CREATE TABLE IF NOT EXISTS workflow_runs (
  workflow_id TEXT PRIMARY KEY,
  workflow_path TEXT,
  status TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  state JSONB
);

CREATE TABLE IF NOT EXISTS workflow_checkpoints (
  workflow_id TEXT PRIMARY KEY,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS workflow_runs_status_idx ON workflow_runs(status);
