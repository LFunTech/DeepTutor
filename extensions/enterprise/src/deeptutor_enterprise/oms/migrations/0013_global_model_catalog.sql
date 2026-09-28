-- OMS 全局模型目录草稿。只有未来逐执行者确认的受控发布流程可更新 active；
-- 本迁移不从现有 tenant 配置或部署文件推断平台生效版本，也不写入凭据明文。
CREATE TABLE oms.model_catalog_config (
  id text PRIMARY KEY,
  version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
  active_version bigint NOT NULL DEFAULT 0 CHECK (active_version >= 0 AND active_version <= version),
  desired jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(desired)='object'),
  active jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(active)='object'),
  status text NOT NULL DEFAULT 'saved',
  updated_by text NOT NULL CHECK (length(trim(updated_by)) > 0),
  updated_at timestamptz NOT NULL DEFAULT now()
);
