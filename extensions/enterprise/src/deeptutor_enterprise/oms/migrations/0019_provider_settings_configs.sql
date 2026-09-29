-- 全服务 Provider/执行者设置的 OMS 版本化事实表。
-- 业务状态值、服务 key、目标确认语义和 legacy JSON 映射均由应用层校验；
-- 本迁移仅定义持久化结构，不使用 DB enum、枚举 CHECK、函数或触发器。
CREATE TABLE oms.provider_setting_configs (
  config_key text PRIMARY KEY,
  version bigint NOT NULL DEFAULT 1,
  desired jsonb NOT NULL DEFAULT '{}'::jsonb,
  active jsonb NOT NULL DEFAULT '{}'::jsonb,
  active_version bigint NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'unconfigured',
  descriptor_version bigint NOT NULL DEFAULT 1,
  updated_by text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE oms.provider_setting_confirmations (
  config_key text NOT NULL,
  version bigint NOT NULL,
  executor_id text NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  observed_at timestamptz,
  safe_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (config_key,version,executor_id)
);

CREATE TABLE oms.provider_setting_import_dry_runs (
  id uuid PRIMARY KEY,
  source_kind text NOT NULL,
  source_hash text NOT NULL,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX provider_setting_confirmations_status
  ON oms.provider_setting_confirmations(config_key,version,status,executor_id);
CREATE INDEX provider_setting_import_dry_runs_source
  ON oms.provider_setting_import_dry_runs(source_kind,source_hash,created_at DESC);
