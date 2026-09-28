-- 在线产品不写入角色动作；模板只由版本化迁移写入并由 Python runner 校验范围。
DROP TRIGGER validate_role_action ON management.role_actions;
DROP FUNCTION management.validate_role_action();
