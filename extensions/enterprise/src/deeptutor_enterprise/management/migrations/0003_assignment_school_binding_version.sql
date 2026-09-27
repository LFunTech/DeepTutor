-- 历史学校授权不猜测原绑定版本；NULL 一律在权限决策中拒绝，须受控复核后重新授权。
ALTER TABLE management.assignments
  ADD COLUMN school_binding_version bigint;
ALTER TABLE management.assignments
  ADD CONSTRAINT assignments_school_binding_version_valid
  CHECK ((scope_kind='platform' AND school_binding_version IS NULL) OR
         (scope_kind='school' AND
          (school_binding_version IS NULL OR school_binding_version>0)));
