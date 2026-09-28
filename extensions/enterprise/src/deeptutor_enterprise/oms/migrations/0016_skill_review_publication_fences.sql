-- 审查事实只追加；发布与授权各自绑定确切的审查/发布版本。
-- 历史草稿/发布/授权未携带这些证明时保持不可用，不自动推断审查通过。
ALTER TABLE oms.skill_revisions
  ADD COLUMN created_issuer text;

CREATE TABLE oms.skill_reviews (
  id uuid PRIMARY KEY,
  revision_id uuid NOT NULL REFERENCES oms.skill_revisions(id),
  content_sha256 text NOT NULL,
  approved boolean NOT NULL,
  scanner_version text NOT NULL,
  code_file_digests jsonb NOT NULL,
  code_review_evidence text NOT NULL DEFAULT '',
  reviewer_issuer text NOT NULL,
  reviewer_subject text NOT NULL,
  reason text NOT NULL,
  request_id text NOT NULL,
  reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(revision_id,reviewer_issuer,reviewer_subject,request_id)
);
CREATE INDEX skill_reviews_latest ON oms.skill_reviews(revision_id,reviewed_at DESC,id DESC);

ALTER TABLE oms.skill_publications
  ADD COLUMN review_id uuid REFERENCES oms.skill_reviews(id),
  ADD COLUMN published_issuer text;

ALTER TABLE oms.skill_grants
  ADD COLUMN publication_version bigint,
  ADD COLUMN granted_issuer text;

ALTER TABLE oms.skill_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE oms.skill_reviews FORCE ROW LEVEL SECURITY;
CREATE POLICY skill_review_oms_scope ON oms.skill_reviews
  USING (current_setting('app.management_app',true)='oms')
  WITH CHECK (current_setting('app.management_app',true)='oms');
