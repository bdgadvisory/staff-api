-- External Services registry + ledger (Phase 1)

CREATE TABLE IF NOT EXISTS external_services (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL,
  vendor TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  criticality TEXT NOT NULL DEFAULT 'important',
  payment_model TEXT NOT NULL DEFAULT 'unknown',
  billing_status TEXT NOT NULL DEFAULT 'invoice_unknown',
  auth_status TEXT NOT NULL DEFAULT 'unknown',
  health_status TEXT NOT NULL DEFAULT 'unknown',
  routing_role TEXT NOT NULL DEFAULT 'unknown',
  owner_department TEXT,
  budget_amount NUMERIC,
  budget_currency TEXT DEFAULT 'USD',
  soft_limit_pct NUMERIC,
  hard_limit_pct NUMERIC,
  billing_cycle TEXT,
  usage_reset_rule TEXT,
  hard_cap_action TEXT,
  fallback_target_service_id UUID REFERENCES external_services(id),
  last_success_at TIMESTAMPTZ,
  last_failure_at TIMESTAMPTZ,
  last_billing_sync_at TIMESTAMPTZ,
  last_auth_check_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS external_service_endpoints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id UUID NOT NULL REFERENCES external_services(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  service_type TEXT NOT NULL DEFAULT 'endpoint',
  unit_type TEXT NOT NULL DEFAULT 'requests',
  input_unit_price NUMERIC,
  output_unit_price NUMERIC,
  flat_price NUMERIC,
  pricing_version TEXT,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(service_id, name)
);

CREATE TABLE IF NOT EXISTS external_service_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
  service_id UUID NOT NULL REFERENCES external_services(id) ON DELETE CASCADE,
  endpoint_id UUID REFERENCES external_service_endpoints(id) ON DELETE SET NULL,
  department TEXT,
  agent TEXT,
  workflow_id TEXT,
  job_id TEXT,
  event_type TEXT NOT NULL,
  success BOOLEAN NOT NULL,
  status_code INT,
  latency_ms INT,
  input_units NUMERIC,
  output_units NUMERIC,
  other_units_json JSONB,
  estimated_cost NUMERIC,
  currency TEXT DEFAULT 'USD',
  error_code TEXT,
  error_summary TEXT,
  raw_metadata_json JSONB
);

CREATE TABLE IF NOT EXISTS external_service_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id UUID NOT NULL REFERENCES external_services(id) ON DELETE CASCADE,
  severity TEXT NOT NULL,
  alert_type TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

-- Seed a minimal registry for known providers (idempotent)
INSERT INTO external_services (name, slug, category, vendor, criticality, payment_model, billing_status, auth_status, health_status, routing_role, owner_department)
VALUES
  ('OpenAI', 'openai', 'llm', 'openai', 'core', 'paid', 'invoice_unknown', 'unknown', 'unknown', 'primary', 'staff'),
  ('Anthropic', 'anthropic', 'llm', 'anthropic', 'important', 'paid', 'invoice_unknown', 'unknown', 'unknown', 'secondary', 'staff'),
  ('Google', 'google', 'llm', 'google', 'optional', 'mixed', 'invoice_unknown', 'unknown', 'unknown', 'fallback', 'staff')
ON CONFLICT (slug) DO NOTHING;
