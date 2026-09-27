-- 学校管理应用只读本校 Webhook 生命周期投影；写入仍只由部署收件箱作用域执行。
CREATE POLICY school_projection_read ON eduplus2.webhook_school_state
  FOR SELECT
  USING (school_id = nullif(current_setting('app.tenant_id',true),'')::uuid);
