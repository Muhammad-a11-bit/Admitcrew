CREATE UNIQUE INDEX IF NOT EXISTS leads_access_token_uidx
  ON public.leads(access_token);
