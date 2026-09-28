-- 自定义 TMS 角色有明确学校 owner；模板和 OMS 角色仍为应用目录事实。
-- 已应用的 0001–0006 不改写；在线程序按 owner 及独立学校授权校验。
ALTER TABLE management.role_versions
  ADD COLUMN owner_school_id uuid REFERENCES enterprise.tenants(id);
ALTER TABLE management.role_actions
  ADD COLUMN owner_school_id uuid REFERENCES enterprise.tenants(id);

CREATE INDEX role_versions_school_owner
  ON management.role_versions(owner_school_id,role_key,version)
  WHERE owner_school_id IS NOT NULL;
CREATE INDEX role_actions_school_owner
  ON management.role_actions(owner_school_id,role_key,role_version)
  WHERE owner_school_id IS NOT NULL;
