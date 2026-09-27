-- 显式绑定内部 UUID 与 EduPlus2 数字学校 ID；不得从 school_code 或 external_tid 自动推断。
-- 只含平台元数据，不含学校私有正文；由受控平台迁移/管理流程写入。
CREATE TABLE oms.school_bindings (
  tenant_id uuid PRIMARY KEY REFERENCES enterprise.tenants(id),
  eduplus_tenant_id bigint NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'pending',
  version bigint NOT NULL DEFAULT 1,
  verified_at timestamptz,
  verified_by text,
  source_ref text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (eduplus_tenant_id > 0),
  CHECK (status IN ('pending','verified','revoked')),
  CHECK (version >= 1),
  CHECK (length(trim(source_ref)) > 0),
  CHECK ((status = 'verified') = (verified_at IS NOT NULL AND verified_by IS NOT NULL
    AND length(trim(verified_by)) > 0))
);
