-- 数据库学校空间与绑定/注册/投影由 created 事件同一事务初始化。
-- 此标记只证明本系统 PG 初始化完成，绝不代表 AI 资源已 ready。
ALTER TABLE eduplus2.webhook_school_state
  ADD COLUMN onboarding_event_id text,
  ADD COLUMN onboarding_completed_at timestamptz,
  ADD CONSTRAINT webhook_school_onboarding_pair
  CHECK ((onboarding_event_id IS NULL AND onboarding_completed_at IS NULL) OR
         (length(onboarding_event_id) BETWEEN 1 AND 128 AND
          onboarding_completed_at IS NOT NULL));
