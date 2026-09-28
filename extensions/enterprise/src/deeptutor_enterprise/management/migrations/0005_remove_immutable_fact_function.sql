-- 在线角色、动作与审计仅由程序追加；模板变更走后续版本化迁移。
-- 不改写已应用 0001，亦不开放运行时 UPDATE/DELETE 事实入口。
DROP TRIGGER role_versions_append_only ON management.role_versions;
DROP TRIGGER role_actions_append_only ON management.role_actions;
DROP TRIGGER audit_events_append_only ON management.audit_events;
DROP FUNCTION management.reject_immutable_fact();
