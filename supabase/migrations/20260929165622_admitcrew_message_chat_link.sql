ALTER TABLE public.outbound_messages
  ADD COLUMN IF NOT EXISTS chat_id bigint REFERENCES public.chats(id);
CREATE INDEX IF NOT EXISTS outbound_messages_chat_id_idx
  ON public.outbound_messages(chat_id);
