-- 原始调用证据与审计事实只追加；核对/更正另写事件，不原地改写。
CREATE FUNCTION oms.reject_fact_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'OMS evidence and audit facts are append-only'
    USING ERRCODE = 'P0001';
END;
$$;

CREATE TRIGGER attempt_evidence_append_only
  BEFORE UPDATE OR DELETE ON oms.attempt_evidence_events
  FOR EACH ROW EXECUTE FUNCTION oms.reject_fact_mutation();

CREATE TRIGGER audit_events_append_only
  BEFORE UPDATE OR DELETE ON oms.audit_events
  FOR EACH ROW EXECUTE FUNCTION oms.reject_fact_mutation();
