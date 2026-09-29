-- Additive-only migration for the AdmitCrew backend and approval workflows.
-- Existing program and lead rows are preserved.
ALTER TABLE public.leads
  ADD COLUMN IF NOT EXISTS access_token text NOT NULL DEFAULT gen_random_uuid()::text;

-- Preserve the same phone while making formatting consistent for deduplication.
UPDATE public.leads
SET phone = regexp_replace(phone, '\D', '', 'g')
WHERE phone ~ '[^0-9]';

ALTER TABLE public.chats
  ADD COLUMN IF NOT EXISTS workflow_status text NOT NULL DEFAULT 'received',
  ADD COLUMN IF NOT EXISTS needs_staff boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS source_program_ids jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE public.outbound_messages
  ADD COLUMN IF NOT EXISTS message_type text NOT NULL DEFAULT 'chat_reply',
  ADD COLUMN IF NOT EXISTS channel text NOT NULL DEFAULT 'website';

ALTER TABLE public.document_reviews
  ADD COLUMN IF NOT EXISTS storage_path text,
  ADD COLUMN IF NOT EXISTS extracted_ielts text;

CREATE INDEX IF NOT EXISTS chats_workflow_status_created_idx
  ON public.chats(workflow_status, created_at);
CREATE INDEX IF NOT EXISTS outbound_messages_status_created_idx
  ON public.outbound_messages(status, created_at);
CREATE INDEX IF NOT EXISTS document_reviews_status_created_idx
  ON public.document_reviews(status, created_at);
