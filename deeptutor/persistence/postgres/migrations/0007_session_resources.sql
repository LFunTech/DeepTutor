-- 随机会话代际与不可复用对象键；候选和待清理记录不随会话物理删除消失。
ALTER TABLE enterprise.sessions ADD COLUMN incarnation uuid NOT NULL DEFAULT gen_random_uuid(),
 ADD COLUMN deletion_token uuid,
 ADD UNIQUE(tenant_id,owner_id,id,incarnation);
CREATE TABLE enterprise.session_objects (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, object_id uuid NOT NULL,
 session_id text NOT NULL, session_ref text, incarnation uuid NOT NULL,
 attachment_id text NOT NULL, filename text NOT NULL, mime_type text NOT NULL,
 byte_size bigint NOT NULL CHECK(byte_size>=0 AND byte_size<=52428800),
 sha256 text NOT NULL, state text NOT NULL CHECK(state IN ('candidate','ready','cleanup','deleted')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0), last_error text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,owner_id,object_id),
 CHECK(session_ref IS NULL OR session_ref=session_id),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES enterprise.users(tenant_id,id),
 FOREIGN KEY(tenant_id,owner_id,session_ref,incarnation) REFERENCES enterprise.sessions(tenant_id,owner_id,id,incarnation)
);
CREATE FUNCTION enterprise.detach_session_objects_before_session_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 UPDATE enterprise.session_objects
    SET session_ref = NULL
  WHERE tenant_id = OLD.tenant_id
    AND owner_id = OLD.owner_id
    AND session_ref = OLD.id
    AND incarnation = OLD.incarnation;
 RETURN OLD;
END $$;
CREATE TRIGGER detach_session_objects_before_session_delete
BEFORE DELETE ON enterprise.sessions
FOR EACH ROW EXECUTE FUNCTION enterprise.detach_session_objects_before_session_delete();
CREATE TABLE enterprise.message_objects (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, session_id text NOT NULL,
 message_id bigint NOT NULL, object_id uuid NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,message_id,object_id),
 FOREIGN KEY(tenant_id,owner_id,session_id,message_id) REFERENCES enterprise.messages(tenant_id,owner_id,session_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,owner_id,object_id) REFERENCES enterprise.session_objects(tenant_id,owner_id,object_id)
);
CREATE INDEX session_objects_pending ON enterprise.session_objects(tenant_id,owner_id,state,created_at,object_id);
CREATE INDEX session_objects_session ON enterprise.session_objects(tenant_id,owner_id,session_ref,incarnation);
CREATE INDEX message_objects_object ON enterprise.message_objects(tenant_id,owner_id,object_id);
CREATE INDEX message_objects_session ON enterprise.message_objects(tenant_id,owner_id,session_id,message_id);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['session_objects','message_objects'] LOOP
  EXECUTE format('ALTER TABLE enterprise.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_scope ON enterprise.%I USING (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  EXECUTE format('CREATE POLICY owner_scope ON enterprise.%I AS RESTRICTIVE USING (owner_id = nullif(current_setting(''app.user_id'',true),'''')) WITH CHECK (owner_id = nullif(current_setting(''app.user_id'',true),''''))',t);
 END LOOP;
END $$;
-- 消息与对象必须属于同一会话，不仅 owner 相同。
ALTER TABLE enterprise.session_objects ADD UNIQUE(tenant_id,owner_id,session_id,object_id);
ALTER TABLE enterprise.message_objects ADD FOREIGN KEY(tenant_id,owner_id,session_id,object_id) REFERENCES enterprise.session_objects(tenant_id,owner_id,session_id,object_id);
CREATE TABLE enterprise.session_references (
 tenant_id uuid NOT NULL, owner_id text NOT NULL, session_id text NOT NULL,
 source_kind text NOT NULL CHECK(source_kind IN ('preferences','message','turn')),
 source_id text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('mastery_path_id','reading_workspace_id','reading_material_id')),
 target_id text NOT NULL CHECK(length(target_id)>0),
 message_ref bigint GENERATED ALWAYS AS (CASE WHEN source_kind='message' THEN source_id::bigint END) STORED,
 turn_ref text GENERATED ALWAYS AS (CASE WHEN source_kind='turn' THEN source_id END) STORED,
 path_ref text GENERATED ALWAYS AS (CASE WHEN kind='mastery_path_id' THEN target_id END) STORED,
 workspace_ref text GENERATED ALWAYS AS (CASE WHEN kind='reading_workspace_id' THEN target_id END) STORED,
 material_ref text GENERATED ALWAYS AS (CASE WHEN kind='reading_material_id' THEN target_id END) STORED,
 PRIMARY KEY(tenant_id,owner_id,session_id,source_kind,source_id,kind,target_id),
 FOREIGN KEY(tenant_id,owner_id,session_id) REFERENCES enterprise.sessions(tenant_id,owner_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,owner_id,session_id,message_ref) REFERENCES enterprise.messages(tenant_id,owner_id,session_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,owner_id,session_id,turn_ref) REFERENCES enterprise.turns(tenant_id,user_id,session_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,owner_id,path_ref) REFERENCES enterprise.mastery_paths(tenant_id,owner_id,path_id),
 FOREIGN KEY(tenant_id,owner_id,workspace_ref) REFERENCES enterprise.reading_workspaces(tenant_id,owner_id,workspace_id),
 FOREIGN KEY(tenant_id,owner_id,material_ref) REFERENCES enterprise.reading_materials(tenant_id,owner_id,material_id)
);
CREATE INDEX session_references_message ON enterprise.session_references(tenant_id,owner_id,session_id,message_ref);
CREATE INDEX session_references_turn ON enterprise.session_references(tenant_id,owner_id,session_id,turn_ref);
CREATE INDEX session_references_path ON enterprise.session_references(tenant_id,owner_id,path_ref);
CREATE INDEX session_references_workspace ON enterprise.session_references(tenant_id,owner_id,workspace_ref);
CREATE INDEX session_references_material ON enterprise.session_references(tenant_id,owner_id,material_ref);
ALTER TABLE enterprise.session_references ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON enterprise.session_references USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY owner_scope ON enterprise.session_references AS RESTRICTIVE USING (owner_id = nullif(current_setting('app.user_id',true),'')) WITH CHECK (owner_id = nullif(current_setting('app.user_id',true),''));
-- 已有 PG JSON 引用投影为同一 typed FK；不改正文，不把未知引用默认归给 owner。
-- 坏/缺失来源会使整次升级回滚，必须在维护流程核查而非静默丢弃。
WITH payloads AS (
 SELECT tenant_id,owner_id,id AS session_id,'preferences'::text AS source_kind,''::text AS source_id,preferences AS payload FROM enterprise.sessions
 UNION ALL
 SELECT tenant_id,owner_id,session_id,'message',id::text,jsonb_build_array(metadata,events) FROM enterprise.messages
 UNION ALL
 SELECT tenant_id,owner_id,session_id,'turn',turn_id,event FROM enterprise.turn_events
)
INSERT INTO enterprise.session_references(tenant_id,owner_id,session_id,source_kind,source_id,kind,target_id)
SELECT p.tenant_id,p.owner_id,p.session_id,p.source_kind,p.source_id,ref->>'key',ref->>'value'
FROM payloads p CROSS JOIN LATERAL jsonb_path_query(p.payload,'strict $.** ? (@.type() == "object").keyvalue() ? (@.key == "mastery_path_id" || @.key == "reading_workspace_id" || @.key == "reading_material_id")') ref
WHERE ref->'value' NOT IN ('null'::jsonb,'""'::jsonb)
ON CONFLICT DO NOTHING;

-- 实际请求历史只在 request_snapshot 对象内使用这些 camelCase 字段。
-- 投影 canonical kind，不重写已保存的 JSON；同上方 snake_case 共用 FK。
WITH payloads AS (
 SELECT tenant_id,owner_id,id AS session_id,'preferences'::text AS source_kind,''::text AS source_id,preferences AS payload FROM enterprise.sessions
 UNION ALL
 SELECT tenant_id,owner_id,session_id,'message',id::text,jsonb_build_array(metadata,events) FROM enterprise.messages
 UNION ALL
 SELECT tenant_id,owner_id,session_id,'turn',turn_id,event FROM enterprise.turn_events
), snapshots AS (
 SELECT p.*,ref->'value' AS snapshot
 FROM payloads p CROSS JOIN LATERAL jsonb_path_query(p.payload,'strict $.** ? (@.type() == "object").keyvalue() ? (@.key == "request_snapshot" && @.value.type() == "object")') ref
)
INSERT INTO enterprise.session_references(tenant_id,owner_id,session_id,source_kind,source_id,kind,target_id)
SELECT p.tenant_id,p.owner_id,p.session_id,p.source_kind,p.source_id,
 CASE ref.key WHEN 'masteryPathId' THEN 'mastery_path_id' WHEN 'readingWorkspaceId' THEN 'reading_workspace_id' WHEN 'readingMaterialId' THEN 'reading_material_id' END,
 ref.value #>> '{}'
FROM snapshots p CROSS JOIN LATERAL jsonb_each(p.snapshot) ref
WHERE ref.key IN ('masteryPathId','readingWorkspaceId','readingMaterialId')
 AND ref.value NOT IN ('null'::jsonb,'""'::jsonb)
ON CONFLICT DO NOTHING;

-- 历史未知机器引用只在维护迁移时扫描一次，删除时不再取回/扫描全量 trace。
ALTER TABLE enterprise.sessions ADD COLUMN unresolved_dependencies boolean NOT NULL DEFAULT false;
WITH payloads AS (
 SELECT tenant_id,owner_id,id AS session_id,preferences AS payload FROM enterprise.sessions
 UNION ALL
 SELECT tenant_id,owner_id,session_id,jsonb_build_array(metadata,events) FROM enterprise.messages
 UNION ALL
 SELECT tenant_id,owner_id,session_id,event FROM enterprise.turn_events
), unresolved AS (
 SELECT DISTINCT tenant_id,owner_id,session_id FROM payloads p CROSS JOIN LATERAL jsonb_path_query(p.payload,'strict $.** ? (@.type() == "object").keyvalue() ? (@.key == "attachments" || @.key == "attachment_ids" || @.key == "course_id" || @.key == "material_id" || @.key == "kb_name" || @.key == "kb_id" || @.key == "knowledge_base" || @.key == "notebook_id" || @.key == "notebook_ids" || @.key == "learning_state" || @.key == "external_dependencies" || @.key == "generated_files" || @.key == "file_id" || @.key == "file_ids")') ref
 WHERE ref->'value' NOT IN ('null'::jsonb,'false'::jsonb,'0'::jsonb,'""'::jsonb,'[]'::jsonb,'{}'::jsonb)
)
UPDATE enterprise.sessions s SET unresolved_dependencies=true FROM unresolved u WHERE (s.tenant_id,s.owner_id,s.id)=(u.tenant_id,u.owner_id,u.session_id);
