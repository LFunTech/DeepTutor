-- Persist documented subscription.created actor identifiers for later OIDC contract checks.
-- Raw display names are intentionally not stored by application code; only a hash is kept.
ALTER TABLE eduplus2.lifecycle_inbox
  ADD COLUMN IF NOT EXISTS actor_context jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE eduplus2.lifecycle_actor_candidates
  ADD COLUMN IF NOT EXISTS actor_context jsonb NOT NULL DEFAULT '{}'::jsonb;
