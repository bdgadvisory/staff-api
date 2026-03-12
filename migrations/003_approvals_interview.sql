ALTER TABLE approvals
  ADD COLUMN IF NOT EXISTS interview_questions JSONB,
  ADD COLUMN IF NOT EXISTS interview_answers JSONB;
