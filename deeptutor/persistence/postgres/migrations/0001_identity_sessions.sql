-- 应用结构迁移：只支持本 A1 身份/纯文本会话范围。
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='dt_enterprise_app') THEN
    CREATE ROLE dt_enterprise_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
END $$;
REVOKE ALL ON SCHEMA enterprise FROM PUBLIC;
GRANT USAGE ON SCHEMA enterprise TO dt_enterprise_app;

CREATE TABLE enterprise.tenants (
  id uuid PRIMARY KEY,
  external_tid text,
  external_eligibility text NOT NULL CHECK (external_eligibility IN ('not_required','allowed','denied')),
  local_enabled boolean NOT NULL DEFAULT false,
  provisioning_status text NOT NULL DEFAULT 'pending' CHECK (provisioning_status IN ('pending','ready','failed')),
  external_version bigint NOT NULL DEFAULT 1,
  local_version bigint NOT NULL DEFAULT 1,
  provisioning_version bigint NOT NULL DEFAULT 1,
  policy_version bigint NOT NULL DEFAULT 1,
  auth_epoch text NOT NULL,
  bootstrap_completed boolean NOT NULL DEFAULT false,
  recovery_state text NOT NULL DEFAULT 'normal' CHECK(recovery_state IN ('normal','quarantined'))
);
CREATE TABLE enterprise.users (
  tenant_id uuid NOT NULL REFERENCES enterprise.tenants(id),
  id text NOT NULL CHECK (length(id) BETWEEN 1 AND 255),
  username text NOT NULL CHECK (length(username) BETWEEN 1 AND 128),
  role text NOT NULL CHECK (role IN ('tenant_admin','user')),
  disabled boolean NOT NULL DEFAULT false,
  auth_version bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id,id), UNIQUE(tenant_id,username)
);
CREATE TABLE enterprise.local_credentials (
  tenant_id uuid NOT NULL, user_id text NOT NULL, password_hash text NOT NULL,
  PRIMARY KEY (tenant_id,user_id),
  FOREIGN KEY (tenant_id,user_id) REFERENCES enterprise.users(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE enterprise.auth_sessions (
  tenant_id uuid NOT NULL, user_id text NOT NULL, id uuid NOT NULL,
  auth_version bigint NOT NULL, auth_epoch text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  PRIMARY KEY (tenant_id,id),
  FOREIGN KEY (tenant_id,user_id) REFERENCES enterprise.users(tenant_id,id) ON DELETE CASCADE
);
CREATE INDEX ON enterprise.auth_sessions (tenant_id,user_id);
CREATE TABLE enterprise.audit (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, tenant_id uuid NOT NULL,
  actor_id text NOT NULL, action text NOT NULL, target_id text NOT NULL,
  request_id text NOT NULL, result text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE enterprise.sessions (
  tenant_id uuid NOT NULL, owner_id text NOT NULL, id text NOT NULL,
  title text NOT NULL DEFAULT 'New conversation', summary text NOT NULL DEFAULT '',
  summary_up_to_msg_id bigint, preferences jsonb NOT NULL DEFAULT '{}',
  parent_session_id text, active_leaf_id bigint,
  pinned boolean NOT NULL DEFAULT false, archived boolean NOT NULL DEFAULT false,
  deleting boolean NOT NULL DEFAULT false, version bigint NOT NULL DEFAULT 1,
  created_at double precision NOT NULL DEFAULT extract(epoch FROM now()),
  updated_at double precision NOT NULL DEFAULT extract(epoch FROM now()),
  PRIMARY KEY (tenant_id,id), UNIQUE(tenant_id,owner_id,id),
  FOREIGN KEY (tenant_id,owner_id) REFERENCES enterprise.users(tenant_id,id),
  FOREIGN KEY (tenant_id,owner_id,parent_session_id) REFERENCES enterprise.sessions(tenant_id,owner_id,id),
  CHECK(parent_session_id IS NULL OR parent_session_id<>id)
);
CREATE TABLE enterprise.messages (
  tenant_id uuid NOT NULL, owner_id text NOT NULL, session_id text NOT NULL,
  id bigint GENERATED ALWAYS AS IDENTITY,
  role text NOT NULL CHECK (role IN ('user','assistant','system','tool')),
  content text NOT NULL, capability text NOT NULL DEFAULT '',
  events jsonb NOT NULL DEFAULT '[]', attachments jsonb NOT NULL DEFAULT '[]', metadata jsonb NOT NULL DEFAULT '{}',
  parent_message_id bigint, created_at double precision NOT NULL DEFAULT extract(epoch FROM now()),
  PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,owner_id,session_id,id),
  FOREIGN KEY(tenant_id,owner_id,session_id) REFERENCES enterprise.sessions(tenant_id,owner_id,id) ON DELETE CASCADE,
  FOREIGN KEY(tenant_id,owner_id,session_id,parent_message_id) REFERENCES enterprise.messages(tenant_id,owner_id,session_id,id) DEFERRABLE INITIALLY DEFERRED,
  CHECK(parent_message_id IS NULL OR parent_message_id < id)
);
ALTER TABLE enterprise.sessions ADD FOREIGN KEY(tenant_id,owner_id,id,active_leaf_id)
  REFERENCES enterprise.messages(tenant_id,owner_id,session_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE enterprise.sessions ADD FOREIGN KEY(tenant_id,owner_id,id,summary_up_to_msg_id)
  REFERENCES enterprise.messages(tenant_id,owner_id,session_id,id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE enterprise.turns (
  tenant_id uuid NOT NULL, user_id text NOT NULL, session_id text NOT NULL, id text NOT NULL,
  capability text NOT NULL DEFAULT '', status text NOT NULL DEFAULT 'running'
    CHECK(status IN ('queued','running','waiting_input','completed','cancelled','failed')),
  owner_id text NOT NULL DEFAULT '', fencing_token bigint NOT NULL DEFAULT 0,
  error text NOT NULL DEFAULT '', failure_code text NOT NULL DEFAULT '', retryable boolean NOT NULL DEFAULT false,
  assistant_message_id bigint, user_message_id bigint, next_seq bigint NOT NULL DEFAULT 0,
  state_version bigint NOT NULL DEFAULT 1, finished_at double precision,
  created_at double precision NOT NULL DEFAULT extract(epoch FROM now()),
  updated_at double precision NOT NULL DEFAULT extract(epoch FROM now()),
  PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,user_id,session_id,id),
  FOREIGN KEY(tenant_id,user_id,session_id) REFERENCES enterprise.sessions(tenant_id,owner_id,id) ON DELETE CASCADE,
  FOREIGN KEY(tenant_id,user_id,session_id,user_message_id) REFERENCES enterprise.messages(tenant_id,owner_id,session_id,id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(tenant_id,user_id,session_id,assistant_message_id) REFERENCES enterprise.messages(tenant_id,owner_id,session_id,id) DEFERRABLE INITIALLY DEFERRED
);
CREATE UNIQUE INDEX one_active_turn ON enterprise.turns(tenant_id,session_id)
  WHERE status IN ('queued','running','waiting_input');
CREATE TABLE enterprise.turn_events (
  tenant_id uuid NOT NULL, owner_id text NOT NULL, session_id text NOT NULL, turn_id text NOT NULL,
  seq bigint NOT NULL CHECK(seq>0), event jsonb NOT NULL,
  PRIMARY KEY(tenant_id,turn_id,seq),
  FOREIGN KEY(tenant_id,owner_id,session_id,turn_id) REFERENCES enterprise.turns(tenant_id,user_id,session_id,id) ON DELETE CASCADE
);
CREATE TABLE enterprise.operations (
  tenant_id uuid NOT NULL, owner_id text NOT NULL, operation_id text NOT NULL,
  fingerprint text NOT NULL, request jsonb, session_id text, turn_id text,
  status text NOT NULL DEFAULT 'registered' CHECK(status IN ('registered','deleted')),
  expires_at timestamptz NOT NULL DEFAULT now()+interval '30 days',
  PRIMARY KEY(tenant_id,owner_id,operation_id),
  FOREIGN KEY(tenant_id,owner_id) REFERENCES enterprise.users(tenant_id,id),
  FOREIGN KEY(tenant_id,owner_id,session_id,turn_id) REFERENCES enterprise.turns(tenant_id,user_id,session_id,id) DEFERRABLE INITIALLY DEFERRED,
  CHECK((status='deleted' AND request IS NULL AND session_id IS NULL AND turn_id IS NULL)
    OR (status='registered' AND request IS NOT NULL AND session_id IS NOT NULL AND turn_id IS NOT NULL))
);

CREATE TABLE enterprise.turn_commands (
  tenant_id uuid NOT NULL, owner_id text NOT NULL, session_id text NOT NULL, turn_id text NOT NULL,
  command_id text NOT NULL, kind text NOT NULL CHECK(kind IN ('reply','cancel')),
  fingerprint text NOT NULL, accepted boolean NOT NULL, state_version bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,owner_id,turn_id,command_id),
  FOREIGN KEY(tenant_id,owner_id,session_id,turn_id) REFERENCES enterprise.turns(tenant_id,user_id,session_id,id) ON DELETE CASCADE
);

-- tenant 保护作用于所有租户表，个人内容额外带 owner，管理员没有旁路。
DO $$ DECLARE t text; owner_column text; BEGIN
  FOREACH t IN ARRAY ARRAY['tenants','users','local_credentials','auth_sessions','audit','sessions','messages','turns','turn_events','operations','turn_commands'] LOOP
    EXECUTE format('ALTER TABLE enterprise.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE enterprise.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY tenant_scope ON enterprise.%I USING (%I = nullif(current_setting(''app.tenant_id'', true),'''')::uuid) WITH CHECK (%I = nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t,CASE WHEN t='tenants' THEN 'id' ELSE 'tenant_id' END,CASE WHEN t='tenants' THEN 'id' ELSE 'tenant_id' END);
    IF t IN ('sessions','messages','turns','turn_events','operations','turn_commands') THEN
      owner_column := CASE WHEN t='turns' THEN 'user_id' ELSE 'owner_id' END;
      EXECUTE format('CREATE POLICY owner_scope ON enterprise.%I AS RESTRICTIVE USING (%I = nullif(current_setting(''app.user_id'',true),'''')) WITH CHECK (%I = nullif(current_setting(''app.user_id'',true),''''))',t,owner_column,owner_column);
    END IF;
  END LOOP;
END $$;
GRANT SELECT,INSERT,UPDATE,DELETE ON enterprise.tenants,enterprise.users,enterprise.local_credentials,enterprise.auth_sessions,
  enterprise.sessions,enterprise.messages,enterprise.turns,enterprise.turn_events,enterprise.operations,enterprise.turn_commands TO dt_enterprise_app;
GRANT SELECT,INSERT ON enterprise.audit TO dt_enterprise_app;
GRANT SELECT ON enterprise.schema_history TO dt_enterprise_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA enterprise TO dt_enterprise_app;
-- 进程执行登记不承载业务正文，独立于 tenant 表，未知退出须人工确认。
CREATE TABLE enterprise.executor_state (
  resource text PRIMARY KEY, execution_id uuid NOT NULL,
  status text NOT NULL CHECK(status IN ('active','stopped')),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT,INSERT,UPDATE ON enterprise.executor_state TO dt_enterprise_app;
