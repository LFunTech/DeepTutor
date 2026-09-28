-- 新动作只登记在 DeepTutor Enterprise；不自动登记主体或给现有 assignment 扩权。
-- 保留 v1 模板与历史 assignment，新 v2 模板须经本产品的受控授权流程显式授予。
-- 迁移事务的受限 owner 仍受 FORCE RLS 约束，显式选定 OMS 应用域。
SELECT set_config('app.management_app','oms',true);

INSERT INTO management.action_catalog(application,action_key,allowed_scope,sensitive) VALUES
('oms','ops.skills.read','platform',false),
('oms','ops.skills.manage','platform',true),
('oms','ops.skills.review','platform',true),
('oms','ops.skills.publish','platform',true),
('oms','ops.skills.grant','school',true);

INSERT INTO management.role_versions(application,role_key,version,scope_kind,is_template)
SELECT application,role_key,2,scope_kind,true
  FROM management.role_versions
 WHERE application='oms' AND version=1
   AND role_key IN ('platform_security_admin','platform_config_admin','platform_operator');

INSERT INTO management.role_actions(application,role_key,role_version,action_key)
SELECT ra.application,ra.role_key,2,ra.action_key
  FROM management.role_actions ra
 WHERE ra.application='oms' AND ra.role_version=1
   AND ra.role_key IN ('platform_security_admin','platform_config_admin','platform_operator');

INSERT INTO management.role_actions(application,role_key,role_version,action_key) VALUES
('oms','platform_security_admin',2,'ops.skills.read'),
('oms','platform_security_admin',2,'ops.skills.review'),
('oms','platform_config_admin',2,'ops.skills.read'),
('oms','platform_config_admin',2,'ops.skills.manage'),
('oms','platform_config_admin',2,'ops.skills.publish'),
('oms','platform_operator',2,'ops.skills.grant');
