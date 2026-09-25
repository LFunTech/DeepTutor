-- 学习权威聚合与来源索引。历史孤儿 FK 验证失败时整次升级回滚，须离线修复后重跑。
CREATE TABLE enterprise.mastery_paths (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, path_id text NOT NULL,
 state jsonb NOT NULL CHECK(jsonb_typeof(state)='object'),
 revision bigint NOT NULL CHECK(revision>=0),
 creator_session_id text, creator_assigned boolean NOT NULL DEFAULT false,
 created_at double precision NOT NULL, updated_at double precision NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,path_id),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES enterprise.users(tenant_id,id),
 FOREIGN KEY(tenant_id,owner_id,creator_session_id) REFERENCES enterprise.sessions(tenant_id,owner_id,id)
);
-- 仅来源身份投影，不复制教学内容。已移除知识点保留 retired 供历史题库引用。
CREATE TABLE enterprise.mastery_knowledge_points (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, path_id text NOT NULL, kp_id text NOT NULL,
 active boolean NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,path_id,kp_id),
 FOREIGN KEY(tenant_id,owner_id,path_id) REFERENCES enterprise.mastery_paths ON DELETE CASCADE
);
CREATE TABLE enterprise.mastery_path_sessions (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, path_id text NOT NULL, session_id text NOT NULL,
 created_at double precision NOT NULL, last_seen_at double precision NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,session_id),
 FOREIGN KEY(tenant_id,owner_id,path_id) REFERENCES enterprise.mastery_paths ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,owner_id,session_id) REFERENCES enterprise.sessions(tenant_id,owner_id,id) ON DELETE CASCADE
);
CREATE TABLE enterprise.mastery_interactions (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, path_id text NOT NULL, interaction_id text NOT NULL,
 status text NOT NULL CHECK(status IN ('registered','awaiting_input','answered','graded','abandoned')),
 question jsonb NOT NULL CHECK(jsonb_typeof(question)='object'),
 session_id text NOT NULL DEFAULT '', turn_id text NOT NULL DEFAULT '',
 session_ref text GENERATED ALWAYS AS (nullif(session_id,'')) STORED,
 turn_ref text GENERATED ALWAYS AS (nullif(turn_id,'')) STORED,
 user_answer text NOT NULL DEFAULT '', result jsonb NOT NULL DEFAULT '{}',
 created_at double precision NOT NULL, updated_at double precision NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,interaction_id),
 FOREIGN KEY(tenant_id,owner_id,path_id) REFERENCES enterprise.mastery_paths ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,owner_id,session_ref) REFERENCES enterprise.sessions(tenant_id,owner_id,id),
 FOREIGN KEY(tenant_id,owner_id,session_ref,turn_ref) REFERENCES enterprise.turns(tenant_id,user_id,session_id,id),
 CHECK(turn_id='' OR session_id<>'')
);
CREATE TABLE enterprise.mastery_events (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, path_id text NOT NULL,
 id bigint GENERATED ALWAYS AS IDENTITY, revision bigint NOT NULL CHECK(revision>0),
 event_type text NOT NULL CHECK(length(event_type)>0), payload jsonb NOT NULL,
 session_id text NOT NULL DEFAULT '', turn_id text NOT NULL DEFAULT '',
 session_ref text GENERATED ALWAYS AS (nullif(session_id,'')) STORED,
 turn_ref text GENERATED ALWAYS AS (nullif(turn_id,'')) STORED,
 created_at double precision NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,id),
 FOREIGN KEY(tenant_id,owner_id,path_id) REFERENCES enterprise.mastery_paths ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,owner_id,session_ref) REFERENCES enterprise.sessions(tenant_id,owner_id,id),
 FOREIGN KEY(tenant_id,owner_id,session_ref,turn_ref) REFERENCES enterprise.turns(tenant_id,user_id,session_id,id),
 CHECK(turn_id='' OR session_id<>'')
);
CREATE TABLE enterprise.mastery_topic_meta (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, path_id text NOT NULL,
 goal text NOT NULL, description text NOT NULL, emoji text NOT NULL, map_seed bigint NOT NULL,
 status text NOT NULL CHECK(status IN ('active','archived')),
 created_at double precision NOT NULL, updated_at double precision NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,path_id),
 FOREIGN KEY(tenant_id,owner_id,path_id) REFERENCES enterprise.mastery_paths ON DELETE CASCADE
);
CREATE TABLE enterprise.mastery_topic_sources (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, path_id text NOT NULL, id text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('goal','book','notebook','knowledge_base','file','chat','question_bank','cowriter','partner_group')),
 external_id text NOT NULL, label text NOT NULL, excerpt text NOT NULL,
 position integer NOT NULL CHECK(position>=0), available boolean NOT NULL, metadata jsonb NOT NULL,
 created_at double precision NOT NULL,
 session_ref text GENERATED ALWAYS AS (CASE WHEN kind='chat' AND external_id NOT LIKE 'partner:%' THEN nullif(external_id,'') END) STORED,
 entry_ref bigint GENERATED ALWAYS AS (CASE WHEN kind='question_bank' THEN external_id::bigint END) STORED,
 PRIMARY KEY(tenant_id,owner_id,path_id,id), UNIQUE(tenant_id,owner_id,path_id,position),
 FOREIGN KEY(tenant_id,owner_id,path_id) REFERENCES enterprise.mastery_paths ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,owner_id,session_ref) REFERENCES enterprise.sessions(tenant_id,owner_id,id),
 FOREIGN KEY(tenant_id,owner_id,entry_ref) REFERENCES enterprise.notebook_entries(tenant_id,owner_id,id),
 CHECK(kind<>'chat' OR external_id<>'')
);
-- 本人路径管理不是会话 turn，不需要管理员角色，也不制造隐藏会话。
CREATE TABLE enterprise.mastery_path_operations (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, path_id text NOT NULL, path_ref text, operation_id uuid NOT NULL,
 executor_resource text NOT NULL, execution_id uuid NOT NULL, executor_pid integer NOT NULL,
 status text NOT NULL CHECK(status IN ('active','completed','failed','interrupted')),
 version bigint NOT NULL CHECK(version>0),
 created_at double precision NOT NULL, updated_at double precision NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,operation_id),
 UNIQUE(tenant_id,owner_id,path_id,operation_id),
 CHECK(path_ref=path_id OR path_ref IS NULL),
 CHECK(status<>'active' OR path_ref IS NOT NULL),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES enterprise.users(tenant_id,id),
 FOREIGN KEY(tenant_id,owner_id,path_ref) REFERENCES enterprise.mastery_paths(tenant_id,owner_id,path_id)
);
CREATE FUNCTION enterprise.detach_mastery_path_operations_before_path_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 UPDATE enterprise.mastery_path_operations
    SET path_ref = NULL
  WHERE tenant_id = OLD.tenant_id
    AND owner_id = OLD.owner_id
    AND path_ref = OLD.path_id;
 RETURN OLD;
END $$;
CREATE TRIGGER detach_mastery_path_operations_before_path_delete
BEFORE DELETE ON enterprise.mastery_paths
FOR EACH ROW EXECUTE FUNCTION enterprise.detach_mastery_path_operations_before_path_delete();
CREATE TABLE enterprise.mastery_path_leases (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, path_id text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('turn','operation')),
 session_id text, turn_id text, operation_id uuid,
 executor_resource text NOT NULL, execution_id uuid NOT NULL, executor_pid integer NOT NULL,
 worker_id text, fencing_token bigint, version bigint NOT NULL CHECK(version>0),
 acquired_at double precision NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,path_id), UNIQUE(tenant_id,owner_id,turn_id),
 UNIQUE(tenant_id,owner_id,operation_id),
 FOREIGN KEY(tenant_id,owner_id,path_id) REFERENCES enterprise.mastery_paths ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,owner_id,session_id,turn_id) REFERENCES enterprise.turns(tenant_id,user_id,session_id,id),
 FOREIGN KEY(tenant_id,owner_id,path_id,operation_id) REFERENCES enterprise.mastery_path_operations(tenant_id,owner_id,path_id,operation_id),
 CHECK((kind='turn' AND session_id IS NOT NULL AND turn_id IS NOT NULL AND worker_id IS NOT NULL AND fencing_token IS NOT NULL AND operation_id IS NULL)
 OR (kind='operation' AND session_id IS NULL AND turn_id IS NULL AND worker_id IS NULL AND fencing_token IS NULL AND operation_id IS NOT NULL))
);
ALTER TABLE enterprise.notebook_entries
 ADD COLUMN mastery_path_ref text GENERATED ALWAYS AS (CASE WHEN source='mastery_path' THEN nullif(material_id,'') END) STORED,
 ADD COLUMN mastery_kp_ref text GENERATED ALWAYS AS (CASE WHEN source='mastery_path' THEN nullif(section_id,'') END) STORED,
 ADD CONSTRAINT notebook_mastery_path_required CHECK(source<>'mastery_path' OR material_id<>''),
 ADD FOREIGN KEY(tenant_id,owner_id,mastery_path_ref) REFERENCES enterprise.mastery_paths(tenant_id,owner_id,path_id),
 ADD FOREIGN KEY(tenant_id,owner_id,mastery_path_ref,mastery_kp_ref) REFERENCES enterprise.mastery_knowledge_points(tenant_id,owner_id,path_id,kp_id);
CREATE INDEX mastery_paths_recent ON enterprise.mastery_paths(tenant_id,owner_id,updated_at DESC,path_id DESC);
CREATE INDEX mastery_paths_creator ON enterprise.mastery_paths(tenant_id,owner_id,creator_session_id);
CREATE INDEX mastery_sessions_path ON enterprise.mastery_path_sessions(tenant_id,owner_id,path_id,last_seen_at DESC,session_id DESC);
CREATE UNIQUE INDEX mastery_one_active_question ON enterprise.mastery_interactions(tenant_id,owner_id,path_id) WHERE status IN ('registered','awaiting_input','answered');
CREATE INDEX mastery_interactions_recent ON enterprise.mastery_interactions(tenant_id,owner_id,path_id,created_at DESC,interaction_id DESC);
CREATE INDEX mastery_events_cursor ON enterprise.mastery_events(tenant_id,owner_id,path_id,revision,id);
CREATE INDEX mastery_meta_status ON enterprise.mastery_topic_meta(tenant_id,owner_id,status,path_id);
CREATE INDEX mastery_sources_session ON enterprise.mastery_topic_sources(tenant_id,owner_id,session_ref);
CREATE INDEX mastery_sources_entry ON enterprise.mastery_topic_sources(tenant_id,owner_id,entry_ref);
CREATE INDEX mastery_operations_executor ON enterprise.mastery_path_operations(tenant_id,owner_id,execution_id,status);
CREATE INDEX notebook_mastery_ref ON enterprise.notebook_entries(tenant_id,owner_id,mastery_path_ref,mastery_kp_ref);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['mastery_paths','mastery_knowledge_points','mastery_path_sessions','mastery_interactions','mastery_events','mastery_topic_meta','mastery_topic_sources','mastery_path_operations','mastery_path_leases'] LOOP
  EXECUTE format('ALTER TABLE enterprise.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_scope ON enterprise.%I USING (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  EXECUTE format('CREATE POLICY owner_scope ON enterprise.%I AS RESTRICTIVE USING (owner_id = nullif(current_setting(''app.user_id'',true),'''')) WITH CHECK (owner_id = nullif(current_setting(''app.user_id'',true),''''))',t);
 END LOOP;
END $$;
-- 被引用资源删除时按scope定位，避免历史交互/事件/operation的全表FK检查。
CREATE INDEX mastery_interactions_session ON enterprise.mastery_interactions(tenant_id,owner_id,session_ref,turn_ref);
CREATE INDEX mastery_events_session ON enterprise.mastery_events(tenant_id,owner_id,session_ref,turn_ref);
CREATE INDEX mastery_leases_session ON enterprise.mastery_path_leases(tenant_id,owner_id,session_id,turn_id);
CREATE INDEX mastery_operations_path ON enterprise.mastery_path_operations(tenant_id,owner_id,path_ref);
