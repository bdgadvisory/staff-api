-- 005_reminders.sql
-- External-only reminders with optional RRULE recurrence.

CREATE TABLE IF NOT EXISTS reminders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  message TEXT NOT NULL,

  next_fire_at TIMESTAMPTZ NOT NULL,
  timezone TEXT NOT NULL,

  rrule TEXT,

  status TEXT NOT NULL DEFAULT 'scheduled'
    CHECK (status IN ('scheduled','paused','done','error')),

  target_channel TEXT NOT NULL
    CHECK (target_channel IN ('whatsapp','email')),

  -- For whatsapp: E.164 phone number (e.g. +15551234567)
  -- For email: email address
  target_address TEXT NOT NULL,

  last_fired_at TIMESTAMPTZ,
  last_error TEXT,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reminders_due
  ON reminders(status, next_fire_at);
