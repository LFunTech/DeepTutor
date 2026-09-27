-- 在线资格证明必须绑定学校权威版本；旧版证明一律失效，等待重新核验。
ALTER TABLE eduplus2.lifecycle_targets
  ADD COLUMN binding_version bigint NOT NULL DEFAULT 0;

UPDATE eduplus2.lifecycle_targets
   SET eligibility='unknown', verified_client_id='', resolve_etag='',
       proof_checked_at=NULL, proof_expires_at=NULL, binding_version=0,
       retry_count=0, updated_at=clock_timestamp()
 WHERE eligibility='allowed';

ALTER TABLE eduplus2.lifecycle_targets
  ADD CONSTRAINT lifecycle_allowed_requires_binding_version
  CHECK (eligibility <> 'allowed' OR binding_version > 0);
