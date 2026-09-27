-- Webhook 来源候选只有待核验、已消费、已撤销三态；终态不可被事件重投复活。
ALTER TABLE eduplus2.lifecycle_actor_candidates
  ADD COLUMN resolved_at timestamptz;

ALTER TABLE eduplus2.lifecycle_actor_candidates
  DROP CONSTRAINT lifecycle_actor_candidates_status_check;
ALTER TABLE eduplus2.lifecycle_actor_candidates
  ADD CONSTRAINT lifecycle_actor_candidate_status_check
  CHECK (status IN ('pending_verification','consumed','revoked'));
ALTER TABLE eduplus2.lifecycle_actor_candidates
  ADD CONSTRAINT lifecycle_actor_candidate_resolution_check
  CHECK ((status='pending_verification' AND resolved_at IS NULL) OR
         (status IN ('consumed','revoked') AND resolved_at IS NOT NULL));

CREATE FUNCTION eduplus2.guard_lifecycle_actor_candidate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'lifecycle actor candidate cannot be deleted'
      USING ERRCODE='23514';
  END IF;
  IF (NEW.tenant_id,NEW.event_id,NEW.school_id,NEW.external_tenant_id,
      NEW.external_app_id,NEW.external_subscription_id,NEW.binding_version,
      NEW.actor_issuer,NEW.actor_subject,NEW.received_at)
     IS DISTINCT FROM
     (OLD.tenant_id,OLD.event_id,OLD.school_id,OLD.external_tenant_id,
      OLD.external_app_id,OLD.external_subscription_id,OLD.binding_version,
      OLD.actor_issuer,OLD.actor_subject,OLD.received_at)
     OR (OLD.status<>'pending_verification' AND
         (NEW.status,NEW.resolved_at) IS DISTINCT FROM (OLD.status,OLD.resolved_at))
     OR (OLD.status='pending_verification' AND NEW.status='pending_verification'
         AND NEW.resolved_at IS DISTINCT FROM OLD.resolved_at) THEN
    RAISE EXCEPTION 'lifecycle actor candidate facts and terminal state are immutable'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_lifecycle_actor_candidate BEFORE UPDATE OR DELETE
  ON eduplus2.lifecycle_actor_candidates FOR EACH ROW
  EXECUTE FUNCTION eduplus2.guard_lifecycle_actor_candidate();
