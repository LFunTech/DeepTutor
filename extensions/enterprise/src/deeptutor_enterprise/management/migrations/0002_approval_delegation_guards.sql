-- 已应用 0001 不得改写；补齐审批独立复核与委托范围的数据库底线。
ALTER TABLE management.approval_requests
  ADD CONSTRAINT approval_reviewer_pair_complete
  CHECK ((reviewer_issuer IS NULL AND reviewer_subject IS NULL) OR
         (reviewer_issuer IS NOT NULL AND reviewer_subject IS NOT NULL
          AND length(trim(reviewer_issuer))>0 AND length(trim(reviewer_subject))>0));

ALTER TABLE management.approval_requests
  ADD CONSTRAINT approval_distinct_reviewer
  CHECK (status<>'approved' OR
         (reviewer_issuer IS NOT NULL AND reviewer_subject IS NOT NULL
          AND decided_at IS NOT NULL
          AND (reviewer_issuer,reviewer_subject)<>(proposer_issuer,proposer_subject)));

CREATE FUNCTION management.validate_delegation_policy() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE principal_school uuid;
DECLARE action_scope text;
BEGIN
  SELECT school_id INTO principal_school FROM management.principals
    WHERE id=NEW.principal_id AND application=NEW.application;
  SELECT allowed_scope INTO action_scope FROM management.action_catalog
    WHERE application=NEW.application AND action_key=NEW.action_key AND status='active';
  IF NEW.application='tms' AND principal_school IS DISTINCT FROM NEW.school_id THEN
    RAISE EXCEPTION 'TMS delegation school differs from principal school'
      USING ERRCODE='23514';
  END IF;
  IF action_scope IS NULL OR (action_scope<>'both' AND action_scope<>NEW.scope_kind) THEN
    RAISE EXCEPTION 'delegation action scope is not allowed' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER validate_delegation_policy BEFORE INSERT OR UPDATE
  ON management.delegation_policies FOR EACH ROW
  EXECUTE FUNCTION management.validate_delegation_policy();
