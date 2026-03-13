-- 004_nestor_core.sql
-- Core Nestor storage: users, threads, messages (with optional transcription)

CREATE TABLE IF NOT EXISTS nestor_users (
  id TEXT PRIMARY KEY,
  display_name TEXT,
  role TEXT NOT NULL DEFAULT 'family_user', -- family_user|business_user|admin
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS nestor_threads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  channel TEXT NOT NULL,                 -- whatsapp|email
  external_thread_id TEXT NOT NULL,      -- whatsapp chat id / email thread id
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(channel, external_thread_id)
);

CREATE TABLE IF NOT EXISTS nestor_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id UUID REFERENCES nestor_threads(id) ON DELETE SET NULL,

  channel TEXT NOT NULL,                 -- whatsapp|email
  external_message_id TEXT,              -- provider message id (optional)
  sender_user_id TEXT,                   -- maps to nestor_users.id (optional)
  sender_display TEXT,                   -- raw display for audit/debug

  text TEXT,                             -- original text (nullable for voice)
  media_type TEXT,                       -- audio/voice_note/image/etc
  media_ref TEXT,                        -- provider media id/url (or temp ref)

  transcript_text TEXT,
  transcript_language TEXT,
  transcript_model TEXT,
  transcript_status TEXT NOT NULL DEFAULT 'none', -- none|queued|done|error

  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nestor_messages_created_at ON nestor_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_nestor_messages_channel ON nestor_messages(channel);
