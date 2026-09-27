-- 本产品权限独立于 EduPlus2；只登记模板，不从旧 admin/eit 数据生成主体或授权。
-- 所有管理写操作由企业授权服务按当前外部状态与 PG policy_version 再次校验。
CREATE TABLE management.principals (
  id uuid PRIMARY KEY,
  application text NOT NULL CHECK (application IN ('oms','tms')),
  issuer text NOT NULL CHECK (length(trim(issuer)) > 0),
  subject text NOT NULL CHECK (length(trim(subject)) > 0),
  school_id uuid REFERENCES enterprise.tenants(id),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','disabled')),
  policy_version bigint NOT NULL DEFAULT 1 CHECK (policy_version > 0),
  external_evidence_ref text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id,application),
  CHECK ((application='oms' AND school_id IS NULL) OR
         (application='tms' AND school_id IS NOT NULL))
);
CREATE UNIQUE INDEX principals_oms_identity
  ON management.principals(issuer,subject) WHERE application='oms';
CREATE UNIQUE INDEX principals_tms_identity
  ON management.principals(issuer,subject,school_id) WHERE application='tms';

CREATE TABLE management.action_catalog (
  application text NOT NULL CHECK (application IN ('oms','tms')),
  action_key text NOT NULL,
  allowed_scope text NOT NULL CHECK (allowed_scope IN ('platform','school','both')),
  sensitive boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','retired')),
  version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
  PRIMARY KEY (application,action_key),
  CHECK ((application='oms' AND action_key LIKE 'ops.%') OR
         (application='tms' AND action_key LIKE 'tenant.%')),
  CHECK (application='oms' OR allowed_scope='school')
);

CREATE TABLE management.role_versions (
  application text NOT NULL CHECK (application IN ('oms','tms')),
  role_key text NOT NULL CHECK (length(trim(role_key)) > 0),
  version bigint NOT NULL CHECK (version > 0),
  scope_kind text NOT NULL CHECK (scope_kind IN ('platform','school')),
  is_template boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (application,role_key,version),
  CHECK (application='oms' OR scope_kind='school')
);
CREATE TABLE management.role_actions (
  application text NOT NULL,
  role_key text NOT NULL,
  role_version bigint NOT NULL,
  action_key text NOT NULL,
  PRIMARY KEY (application,role_key,role_version,action_key),
  FOREIGN KEY (application,role_key,role_version)
    REFERENCES management.role_versions(application,role_key,version),
  FOREIGN KEY (application,action_key)
    REFERENCES management.action_catalog(application,action_key)
);

CREATE TABLE management.assignments (
  id uuid PRIMARY KEY,
  application text NOT NULL CHECK (application IN ('oms','tms')),
  principal_id uuid NOT NULL,
  role_key text NOT NULL,
  role_version bigint NOT NULL,
  scope_kind text NOT NULL CHECK (scope_kind IN ('platform','school')),
  school_id uuid REFERENCES enterprise.tenants(id),
  valid_from timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
  version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
  command_id uuid NOT NULL UNIQUE,
  created_by text NOT NULL CHECK (length(trim(created_by)) > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  FOREIGN KEY (principal_id,application) REFERENCES management.principals(id,application),
  FOREIGN KEY (application,role_key,role_version)
    REFERENCES management.role_versions(application,role_key,version),
  CHECK (expires_at > valid_from),
  CHECK ((scope_kind='platform' AND school_id IS NULL AND application='oms') OR
         (scope_kind='school' AND school_id IS NOT NULL)),
  CHECK ((status='active' AND revoked_at IS NULL) OR
         (status='revoked' AND revoked_at IS NOT NULL))
);
CREATE INDEX assignments_effective
  ON management.assignments(application,principal_id,scope_kind,school_id,expires_at)
  WHERE status='active';
CREATE UNIQUE INDEX assignments_active_platform_role
  ON management.assignments(principal_id,role_key)
  WHERE status='active' AND scope_kind='platform';
CREATE UNIQUE INDEX assignments_active_school_role
  ON management.assignments(principal_id,role_key,school_id)
  WHERE status='active' AND scope_kind='school';

CREATE TABLE management.delegation_policies (
  id uuid PRIMARY KEY,
  application text NOT NULL CHECK (application IN ('oms','tms')),
  principal_id uuid NOT NULL,
  action_key text NOT NULL,
  scope_kind text NOT NULL CHECK (scope_kind IN ('platform','school')),
  school_id uuid REFERENCES enterprise.tenants(id),
  valid_from timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
  version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
  FOREIGN KEY (principal_id,application) REFERENCES management.principals(id,application),
  FOREIGN KEY (application,action_key) REFERENCES management.action_catalog(application,action_key),
  CHECK (expires_at > valid_from),
  CHECK ((scope_kind='platform' AND school_id IS NULL AND application='oms') OR
         (scope_kind='school' AND school_id IS NOT NULL))
);

CREATE TABLE management.approval_requests (
  id uuid PRIMARY KEY,
  application text NOT NULL CHECK (application IN ('oms','tms')),
  operation text NOT NULL CHECK (operation IN ('platform_grant','delegation_expand','school_activation')),
  target_principal_id uuid NOT NULL,
  school_id uuid REFERENCES enterprise.tenants(id),
  proposer_issuer text NOT NULL,
  proposer_subject text NOT NULL,
  reviewer_issuer text,
  reviewer_subject text,
  external_qualification_ref text NOT NULL DEFAULT '',
  external_qualification_version text NOT NULL DEFAULT '',
  expected_policy_version bigint NOT NULL CHECK (expected_policy_version > 0),
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','rejected','expired','withdrawn','failed')),
  expires_at timestamptz NOT NULL,
  idempotency_key text NOT NULL CHECK (length(trim(idempotency_key)) > 0),
  reason text NOT NULL CHECK (length(trim(reason)) > 0),
  request_id text NOT NULL CHECK (length(trim(request_id)) > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  decided_at timestamptz,
  FOREIGN KEY (target_principal_id,application)
    REFERENCES management.principals(id,application),
  UNIQUE (application,proposer_issuer,proposer_subject,idempotency_key),
  CHECK ((application='oms' AND operation<>'school_activation') OR
         (application='tms' AND operation='school_activation' AND school_id IS NOT NULL)),
  CHECK (reviewer_subject IS NULL OR reviewer_subject<>proposer_subject OR
         reviewer_issuer<>proposer_issuer)
);
CREATE UNIQUE INDEX approval_pending_school_activation
  ON management.approval_requests(school_id)
  WHERE application='tms' AND operation='school_activation' AND status='pending';

CREATE TABLE management.audit_events (
  id uuid PRIMARY KEY,
  application text NOT NULL CHECK (application IN ('oms','tms')),
  school_id uuid REFERENCES enterprise.tenants(id),
  actor_issuer text NOT NULL,
  actor_subject text NOT NULL,
  action_key text NOT NULL,
  target_kind text NOT NULL,
  target_id text NOT NULL,
  request_id text NOT NULL,
  result text NOT NULL CHECK (result IN ('success','denied','conflict','failed')),
  reason text NOT NULL,
  before_version bigint,
  after_version bigint,
  approval_id uuid,
  safe_summary jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(safe_summary)='object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (length(trim(actor_issuer))>0 AND length(trim(actor_subject))>0),
  CHECK (length(trim(action_key))>0 AND length(trim(request_id))>0),
  CHECK ((application='oms' AND action_key LIKE 'ops.%') OR
         (application='tms' AND action_key LIKE 'tenant.%'))
);
CREATE INDEX audit_events_target_time
  ON management.audit_events(application,school_id,created_at DESC,id);

CREATE FUNCTION management.reject_immutable_fact() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'management role and audit facts are append-only' USING ERRCODE='P0001';
END;
$$;
CREATE TRIGGER role_versions_append_only BEFORE UPDATE OR DELETE ON management.role_versions
  FOR EACH ROW EXECUTE FUNCTION management.reject_immutable_fact();
CREATE TRIGGER role_actions_append_only BEFORE UPDATE OR DELETE ON management.role_actions
  FOR EACH ROW EXECUTE FUNCTION management.reject_immutable_fact();
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON management.audit_events
  FOR EACH ROW EXECUTE FUNCTION management.reject_immutable_fact();

-- 已发布动作的范围/敏感级别不可原位扩张；只允许非治理动作单向退役。
CREATE FUNCTION management.validate_action_catalog_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'management action catalog is append-only'
      USING ERRCODE='23514';
  END IF;
  IF NEW.application IS DISTINCT FROM OLD.application
     OR NEW.action_key IS DISTINCT FROM OLD.action_key
     OR NEW.allowed_scope IS DISTINCT FROM OLD.allowed_scope
     OR NEW.sensitive IS DISTINCT FROM OLD.sensitive
     OR NEW.version IS DISTINCT FROM OLD.version
     OR (OLD.status='retired' AND NEW.status<>'retired')
     OR (OLD.action_key IN ('ops.permissions.manage','tenant.permissions.manage')
         AND NEW.status<>'active') THEN
    RAISE EXCEPTION 'management action catalog change is not allowed'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER validate_action_catalog_change BEFORE UPDATE OR DELETE
  ON management.action_catalog FOR EACH ROW
  EXECUTE FUNCTION management.validate_action_catalog_change();

CREATE FUNCTION management.validate_role_action() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE role_scope text;
DECLARE action_scope text;
BEGIN
  SELECT scope_kind INTO role_scope FROM management.role_versions
    WHERE application=NEW.application AND role_key=NEW.role_key AND version=NEW.role_version;
  SELECT allowed_scope INTO action_scope FROM management.action_catalog
    WHERE application=NEW.application AND action_key=NEW.action_key AND status='active';
  IF role_scope IS NULL OR action_scope IS NULL OR
     (action_scope<>'both' AND action_scope<>role_scope) THEN
    RAISE EXCEPTION 'role action scope is not allowed' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER validate_role_action BEFORE INSERT ON management.role_actions
  FOR EACH ROW EXECUTE FUNCTION management.validate_role_action();

-- 租户主体和授权必须与其唯一学校一致；OMS 学校 scope 不产生学校账号。
CREATE FUNCTION management.validate_assignment() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE principal_school uuid;
DECLARE role_scope text;
BEGIN
  SELECT school_id INTO principal_school FROM management.principals
    WHERE id=NEW.principal_id AND application=NEW.application;
  SELECT scope_kind INTO role_scope FROM management.role_versions
    WHERE application=NEW.application AND role_key=NEW.role_key AND version=NEW.role_version;
  IF role_scope IS DISTINCT FROM NEW.scope_kind THEN
    RAISE EXCEPTION 'role and assignment scope differ' USING ERRCODE='23514';
  END IF;
  IF NEW.application='tms' AND principal_school IS DISTINCT FROM NEW.school_id THEN
    RAISE EXCEPTION 'TMS assignment school differs from principal school' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER validate_assignment BEFORE INSERT OR UPDATE ON management.assignments
  FOR EACH ROW EXECUTE FUNCTION management.validate_assignment();

CREATE FUNCTION management.protect_last_administrator() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE admin_action text;
BEGIN
  admin_action := CASE OLD.application
    WHEN 'tms' THEN 'tenant.permissions.manage'
    WHEN 'oms' THEN 'ops.permissions.manage' END;
  IF ((OLD.application='tms' AND OLD.role_key='school_admin' AND OLD.scope_kind='school')
      OR (OLD.application='oms' AND OLD.role_key='platform_security_admin'
          AND OLD.scope_kind='platform'))
     AND OLD.status='active'
     AND (TG_OP='DELETE' OR NEW.status<>'active'
          OR NEW.role_key<>OLD.role_key OR NEW.role_version<>OLD.role_version
          OR NEW.scope_kind<>OLD.scope_kind
          OR NEW.school_id IS DISTINCT FROM OLD.school_id
          OR NEW.principal_id<>OLD.principal_id OR NEW.valid_from>OLD.valid_from
          OR NEW.expires_at<OLD.expires_at)
     AND OLD.valid_from<=now() AND OLD.expires_at>now()
     AND EXISTS (
       SELECT 1 FROM management.role_actions ra
       JOIN management.action_catalog ac
         ON ac.application=ra.application AND ac.action_key=ra.action_key
       WHERE ra.application=OLD.application AND ra.role_key=OLD.role_key
         AND ra.role_version=OLD.role_version AND ra.action_key=admin_action
         AND ac.status='active'
     ) THEN
    PERFORM pg_advisory_xact_lock(
      hashtextextended(COALESCE(OLD.school_id::text,'oms-platform-security'),0));
    IF NOT EXISTS (
      SELECT 1 FROM management.assignments a
      JOIN management.principals p ON p.id=a.principal_id AND p.application=a.application
      JOIN management.role_actions ra ON ra.application=a.application
        AND ra.role_key=a.role_key AND ra.role_version=a.role_version
      JOIN management.action_catalog ac
        ON ac.application=ra.application AND ac.action_key=ra.action_key
      WHERE a.application=OLD.application AND a.school_id IS NOT DISTINCT FROM OLD.school_id
        AND a.role_key=OLD.role_key AND a.id<>OLD.id
        AND a.status='active' AND a.valid_from<=now() AND a.expires_at>now()
        AND p.status='active' AND ra.action_key=admin_action AND ac.status='active'
    ) THEN
      RAISE EXCEPTION 'last active management administrator cannot be revoked'
        USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN COALESCE(NEW,OLD);
END;
$$;
CREATE TRIGGER protect_last_administrator AFTER UPDATE OR DELETE ON management.assignments
  FOR EACH ROW EXECUTE FUNCTION management.protect_last_administrator();

-- 停用或迁走主体同样不能绕过最后一名平台/学校管理员约束。
CREATE FUNCTION management.protect_last_administrator_principal() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE admin_assignment uuid;
DECLARE admin_role text;
DECLARE admin_action text;
BEGIN
  admin_role := CASE OLD.application
    WHEN 'tms' THEN 'school_admin' WHEN 'oms' THEN 'platform_security_admin' END;
  admin_action := CASE OLD.application
    WHEN 'tms' THEN 'tenant.permissions.manage'
    WHEN 'oms' THEN 'ops.permissions.manage' END;
  IF OLD.status='active'
     AND (NEW.status<>'active' OR NEW.school_id IS DISTINCT FROM OLD.school_id) THEN
    SELECT a.id INTO admin_assignment FROM management.assignments a
      JOIN management.role_actions ra ON ra.application=a.application
        AND ra.role_key=a.role_key AND ra.role_version=a.role_version
      JOIN management.action_catalog ac
        ON ac.application=ra.application AND ac.action_key=ra.action_key
      WHERE a.principal_id=OLD.id AND a.application=OLD.application
        AND a.role_key=admin_role AND a.status='active'
        AND a.valid_from<=now() AND a.expires_at>now()
        AND ra.action_key=admin_action AND ac.status='active' LIMIT 1;
    IF admin_assignment IS NOT NULL THEN
      PERFORM pg_advisory_xact_lock(
        hashtextextended(COALESCE(OLD.school_id::text,'oms-platform-security'),0));
      IF NOT EXISTS (
        SELECT 1 FROM management.assignments a
        JOIN management.principals p ON p.id=a.principal_id AND p.application=a.application
        JOIN management.role_actions ra ON ra.application=a.application
          AND ra.role_key=a.role_key AND ra.role_version=a.role_version
        JOIN management.action_catalog ac
          ON ac.application=ra.application AND ac.action_key=ra.action_key
        WHERE a.application=OLD.application
          AND a.school_id IS NOT DISTINCT FROM OLD.school_id
          AND a.role_key=admin_role AND a.principal_id<>OLD.id
          AND a.status='active' AND a.valid_from<=now() AND a.expires_at>now()
          AND p.status='active' AND ra.action_key=admin_action AND ac.status='active'
      ) THEN
        RAISE EXCEPTION 'last active management administrator cannot be disabled'
          USING ERRCODE='23514';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER protect_last_administrator_principal BEFORE UPDATE ON management.principals
  FOR EACH ROW EXECUTE FUNCTION management.protect_last_administrator_principal();

CREATE FUNCTION management.bump_principal_policy_version() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE management.principals
    SET policy_version=policy_version+1,updated_at=now()
    WHERE id=COALESCE(NEW.principal_id,OLD.principal_id)
      AND application=COALESCE(NEW.application,OLD.application);
  RETURN COALESCE(NEW,OLD);
END;
$$;
CREATE TRIGGER assignment_policy_version AFTER INSERT OR UPDATE OR DELETE
  ON management.assignments FOR EACH ROW
  EXECUTE FUNCTION management.bump_principal_policy_version();
CREATE TRIGGER delegation_policy_version AFTER INSERT OR UPDATE OR DELETE
  ON management.delegation_policies FOR EACH ROW
  EXECUTE FUNCTION management.bump_principal_policy_version();

-- 版本化目录/模板为候选配置，绝不插入 principal、assignment 或委托记录。
INSERT INTO management.action_catalog(application,action_key,allowed_scope,sensitive) VALUES
('oms','ops.oms.access','both',false),
('oms','ops.tenants.read','school',false),
('oms','ops.providers.read','platform',false),
('oms','ops.providers.manage','platform',true),
('oms','ops.credentials.manage','platform',true),
('oms','ops.supply.read','both',false),
('oms','ops.supply.manage','both',true),
('oms','ops.entitlements.read','school',false),
('oms','ops.entitlements.manage','school',true),
('oms','ops.quotas.read','school',false),
('oms','ops.quotas.manage','school',true),
('oms','ops.usage.read','school',false),
('oms','ops.cost.read','platform',true),
('oms','ops.audit.read','both',false),
('oms','ops.audit.export','both',true),
('oms','ops.clients.read','school',false),
('oms','ops.jobs.read','school',false),
('oms','ops.reconciliation.manage','school',true),
('oms','ops.permissions.manage','platform',true),
('tms','tenant.tms.access','school',false),
('tms','tenant.members.read','school',false),
('tms','tenant.permissions.manage','school',true),
('tms','tenant.clients.manage','school',true),
('tms','tenant.access.manage','school',true),
('tms','tenant.quotas.read','school',false),
('tms','tenant.usage.read','school',false),
('tms','tenant.kb.manage','school',true),
('tms','tenant.school.bootstrap','school',true);

INSERT INTO management.role_versions(application,role_key,version,scope_kind,is_template) VALUES
('oms','platform_security_admin',1,'platform',true),
('oms','platform_config_admin',1,'platform',true),
('oms','platform_operator',1,'school',true),
('oms','platform_auditor',1,'school',true),
('tms','school_admin',1,'school',true),
('tms','school_operator',1,'school',true),
('tms','school_auditor',1,'school',true);

INSERT INTO management.role_actions(application,role_key,role_version,action_key) VALUES
('oms','platform_security_admin',1,'ops.oms.access'),
('oms','platform_security_admin',1,'ops.permissions.manage'),
('oms','platform_config_admin',1,'ops.oms.access'),
('oms','platform_config_admin',1,'ops.providers.read'),
('oms','platform_config_admin',1,'ops.providers.manage'),
('oms','platform_config_admin',1,'ops.credentials.manage'),
('oms','platform_operator',1,'ops.tenants.read'),
('oms','platform_operator',1,'ops.oms.access'),
('oms','platform_operator',1,'ops.supply.read'),
('oms','platform_operator',1,'ops.supply.manage'),
('oms','platform_operator',1,'ops.entitlements.read'),
('oms','platform_operator',1,'ops.entitlements.manage'),
('oms','platform_operator',1,'ops.quotas.read'),
('oms','platform_operator',1,'ops.quotas.manage'),
('oms','platform_operator',1,'ops.usage.read'),
('oms','platform_auditor',1,'ops.tenants.read'),
('oms','platform_auditor',1,'ops.oms.access'),
('oms','platform_auditor',1,'ops.audit.read'),
('oms','platform_auditor',1,'ops.usage.read'),
('tms','school_admin',1,'tenant.tms.access'),
('tms','school_admin',1,'tenant.members.read'),
('tms','school_admin',1,'tenant.permissions.manage'),
('tms','school_admin',1,'tenant.clients.manage'),
('tms','school_admin',1,'tenant.access.manage'),
('tms','school_admin',1,'tenant.quotas.read'),
('tms','school_admin',1,'tenant.usage.read'),
('tms','school_admin',1,'tenant.kb.manage'),
('tms','school_operator',1,'tenant.tms.access'),
('tms','school_operator',1,'tenant.members.read'),
('tms','school_operator',1,'tenant.clients.manage'),
('tms','school_operator',1,'tenant.access.manage'),
('tms','school_operator',1,'tenant.quotas.read'),
('tms','school_operator',1,'tenant.usage.read'),
('tms','school_auditor',1,'tenant.tms.access'),
('tms','school_auditor',1,'tenant.members.read'),
('tms','school_auditor',1,'tenant.quotas.read'),
('tms','school_auditor',1,'tenant.usage.read');

ALTER TABLE management.principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE management.principals FORCE ROW LEVEL SECURITY;
CREATE POLICY management_scope ON management.principals
  USING (application = NULLIF(current_setting('app.management_app',true),'')
         AND (application='oms' OR school_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid))
  WITH CHECK (application = NULLIF(current_setting('app.management_app',true),'')
         AND (application='oms' OR school_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid));

ALTER TABLE management.action_catalog ENABLE ROW LEVEL SECURITY;
ALTER TABLE management.action_catalog FORCE ROW LEVEL SECURITY;
CREATE POLICY management_scope ON management.action_catalog
  USING (application = NULLIF(current_setting('app.management_app',true),''))
  WITH CHECK (application = NULLIF(current_setting('app.management_app',true),''));
ALTER TABLE management.role_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE management.role_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY management_scope ON management.role_versions
  USING (application = NULLIF(current_setting('app.management_app',true),''))
  WITH CHECK (application = NULLIF(current_setting('app.management_app',true),''));
ALTER TABLE management.role_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE management.role_actions FORCE ROW LEVEL SECURITY;
CREATE POLICY management_scope ON management.role_actions
  USING (application = NULLIF(current_setting('app.management_app',true),''))
  WITH CHECK (application = NULLIF(current_setting('app.management_app',true),''));

ALTER TABLE management.assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE management.assignments FORCE ROW LEVEL SECURITY;
CREATE POLICY management_scope ON management.assignments
  USING (application = NULLIF(current_setting('app.management_app',true),'')
         AND (application='oms' OR school_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid))
  WITH CHECK (application = NULLIF(current_setting('app.management_app',true),'')
         AND (application='oms' OR school_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid));
ALTER TABLE management.delegation_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE management.delegation_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY management_scope ON management.delegation_policies
  USING (application = NULLIF(current_setting('app.management_app',true),'')
         AND (application='oms' OR school_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid))
  WITH CHECK (application = NULLIF(current_setting('app.management_app',true),'')
         AND (application='oms' OR school_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid));
ALTER TABLE management.approval_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE management.approval_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY management_scope ON management.approval_requests
  USING (application = NULLIF(current_setting('app.management_app',true),'')
         AND (application='oms' OR school_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid))
  WITH CHECK (application = NULLIF(current_setting('app.management_app',true),'')
         AND (application='oms' OR school_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid));
ALTER TABLE management.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE management.audit_events FORCE ROW LEVEL SECURITY;
CREATE POLICY management_scope ON management.audit_events
  USING (application = NULLIF(current_setting('app.management_app',true),'')
         AND (application='oms' OR school_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid))
  WITH CHECK (application = NULLIF(current_setting('app.management_app',true),'')
         AND (application='oms' OR school_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid));
