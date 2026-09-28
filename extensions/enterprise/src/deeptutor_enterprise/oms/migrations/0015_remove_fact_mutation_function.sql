-- OMS 证据/审计仅由程序的追加命令写入；历史变更以新事实表示。
-- 不改写已应用 0006；禁止运行时开放 UPDATE/DELETE 事实命令。
DROP TRIGGER attempt_evidence_append_only ON oms.attempt_evidence_events;
DROP TRIGGER audit_events_append_only ON oms.audit_events;
DROP FUNCTION oms.reject_fact_mutation();
