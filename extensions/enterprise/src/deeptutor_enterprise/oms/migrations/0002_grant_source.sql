-- 授予的来源凭据引用必须直接留在授权事实中；旧 0001 不可原地修改。
-- 若先前环境已有 0001 写入，未知来源保持 NULL，后续走显式核对而非伪造回填。
ALTER TABLE oms.quota_grants
  ADD COLUMN source_ref text;

ALTER TABLE oms.quota_grants
  ADD CONSTRAINT quota_grants_source_ref_nonempty
  CHECK (source_ref IS NULL OR length(source_ref) > 0);
