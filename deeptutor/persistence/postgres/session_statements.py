"""受审查的 Session 行级语句：封闭操作集合，不接收或注册任意 SQL。

这里只共享既有 SQL，不承接 SessionService 的输入规范化、审计、依赖检查
或生命周期算法。调用者必须在现有领域算法内组合这些低层操作。
"""

from enum import Enum, auto
from types import MappingProxyType

SQL_CREATE_SESSION_ROW = (
    "INSERT INTO enterprise.sessions(tenant_id,owner_id,id,title) VALUES(%s,%s,%s,%s) RETURNING *"
)
SQL_GET_SESSION_ROW = (
    "SELECT * FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND id=%s"
)
SQL_LOCK_SESSION_ROW = SQL_GET_SESSION_ROW + " FOR UPDATE"


# 顶层展示附件与真实请求快照都必须有同一消息的权威对象登记；不按数量猜测。
SQL_UNREGISTERED_ATTACHMENTS = """SELECT 1 FROM enterprise.messages m
 CROSS JOIN LATERAL jsonb_array_elements(m.attachments ||
   CASE WHEN jsonb_typeof(m.metadata#>'{request_snapshot,attachments}')='array'
        THEN m.metadata#>'{request_snapshot,attachments}' ELSE '[]'::jsonb END) a
 WHERE m.tenant_id=%s AND m.owner_id=%s AND m.session_id=%s
 AND NOT EXISTS (SELECT 1 FROM enterprise.message_objects o
   WHERE o.tenant_id=m.tenant_id AND o.owner_id=m.owner_id AND o.message_id=m.id
     AND o.object_id::text=lower(split_part(a->>'url','/',5))) LIMIT 1"""


SQL_SUMMARY_SESSION_ROW = "SELECT s.*,\n        coalesce(latest.status,'idle') AS status,\n        coalesce(latest.capability,'') AS capability,\n        coalesce(active.id,'') AS active_turn_id,\n        (SELECT count(*) FROM enterprise.messages m WHERE (m.tenant_id,m.owner_id,m.session_id)=(s.tenant_id,s.owner_id,s.id) AND m.role<>'system') AS message_count,\n        coalesce((SELECT content FROM enterprise.messages m WHERE (m.tenant_id,m.owner_id,m.session_id)=(s.tenant_id,s.owner_id,s.id) AND m.role<>'system' AND btrim(content)<>'' ORDER BY id DESC LIMIT 1),'') AS last_message\n        FROM enterprise.sessions s\n        LEFT JOIN LATERAL (SELECT status,capability FROM enterprise.turns t WHERE (t.tenant_id,t.user_id,t.session_id)=(s.tenant_id,s.owner_id,s.id) ORDER BY updated_at DESC,id DESC LIMIT 1) latest ON true\n        LEFT JOIN LATERAL (SELECT id FROM enterprise.turns t WHERE (t.tenant_id,t.user_id,t.session_id)=(s.tenant_id,s.owner_id,s.id) AND status IN ('queued','running','waiting_input') ORDER BY updated_at DESC,id DESC LIMIT 1) active ON true\n        WHERE s.tenant_id=%s AND s.owner_id=%s AND s.id=%s"


class SessionStatement(Enum):
    CREATE_ROW = auto()
    GET_ROW = auto()
    LOCK_ROW = auto()
    SUMMARY_ROW = auto()
    AUDIT = auto()
    UPDATE_TITLE = auto()
    UPDATE_PREFERENCES = auto()
    GET_MESSAGE = auto()
    MESSAGE_PARENTS = auto()
    MASTERYPATH = auto()
    READING_WORKSPACE = auto()
    READING_MATERIAL = auto()
    CLEAR_PREFERENCE_REFS = auto()
    RECORD_PREFERENCE_REF = auto()
    ACTIVE_TURN = auto()
    FOLLOWUP_REF = auto()
    UNREGISTERED_ATTACHMENTS = auto()
    QUEUE_SESSION_OBJECTS = auto()
    TOMBSTONE_SESSION = auto()
    DETACH_CHILDREN = auto()
    DELETE_ROW = auto()


# 模板和参数数量都是发布期常量。没有外部注册、模板构造或 SQL 拼接入口。
_SESSION_STATEMENTS = MappingProxyType(
    {
        SessionStatement.CREATE_ROW: (SQL_CREATE_SESSION_ROW, 2),
        SessionStatement.GET_ROW: (SQL_GET_SESSION_ROW, 1),
        SessionStatement.LOCK_ROW: (SQL_LOCK_SESSION_ROW, 1),
        SessionStatement.SUMMARY_ROW: (SQL_SUMMARY_SESSION_ROW, 1),
        SessionStatement.ACTIVE_TURN: (
            "SELECT id FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND session_id=%s AND status IN ('queued','running','waiting_input') LIMIT 1",
            1,
        ),
        SessionStatement.FOLLOWUP_REF: (
            "SELECT id FROM enterprise.notebook_entries WHERE tenant_id=%s AND owner_id=%s AND followup_session_id=%s AND session_id<>followup_session_id LIMIT 1",
            1,
        ),
        SessionStatement.UNREGISTERED_ATTACHMENTS: (
            SQL_UNREGISTERED_ATTACHMENTS,
            1,
        ),
        SessionStatement.QUEUE_SESSION_OBJECTS: (
            "WITH p AS (SELECT %s::uuid tenant,%s::text owner,%s::text sid,%s::uuid incarnation) UPDATE enterprise.session_objects o SET state='cleanup',updated_at=now() FROM p WHERE o.tenant_id=p.tenant AND o.owner_id=p.owner AND o.session_ref=p.sid AND o.incarnation=p.incarnation AND o.state<>'deleted' RETURNING o.object_id",
            2,
        ),
        SessionStatement.TOMBSTONE_SESSION: (
            "UPDATE enterprise.operations SET status='deleted',request=NULL,session_id=NULL,turn_id=NULL WHERE tenant_id=%s AND owner_id=%s AND session_id=%s RETURNING operation_id",
            1,
        ),
        SessionStatement.DETACH_CHILDREN: (
            "UPDATE enterprise.sessions SET parent_session_id=NULL,preferences=preferences-'parent_session_id',version=version+1 WHERE tenant_id=%s AND owner_id=%s AND parent_session_id=%s RETURNING id",
            1,
        ),
        SessionStatement.DELETE_ROW: (
            "DELETE FROM enterprise.sessions WHERE tenant_id=%s AND owner_id=%s AND id=%s RETURNING id",
            1,
        ),
        SessionStatement.AUDIT: (
            "INSERT INTO enterprise.audit(tenant_id,actor_id,action,target_id,request_id,result) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id",
            4,
        ),
        SessionStatement.UPDATE_TITLE: (
            "WITH p AS (SELECT %s::uuid tenant,%s::text owner,%s::text sid,%s::text title,%s::double precision now) UPDATE enterprise.sessions s SET title=p.title,updated_at=p.now,version=version+1 FROM p WHERE s.tenant_id=p.tenant AND s.owner_id=p.owner AND s.id=p.sid RETURNING s.*",
            3,
        ),
        SessionStatement.UPDATE_PREFERENCES: (
            "WITH p AS (SELECT %s::uuid tenant,%s::text owner,%s::text sid,%s::jsonb prefs,nullif(%s,'')::text parent,%s::boolean pinned,%s::boolean archived,nullif(%s,'')::bigint leaf,%s::double precision now) UPDATE enterprise.sessions s SET preferences=p.prefs,parent_session_id=p.parent,pinned=p.pinned,archived=p.archived,active_leaf_id=p.leaf,updated_at=p.now,version=version+1 FROM p WHERE s.tenant_id=p.tenant AND s.owner_id=p.owner AND s.id=p.sid RETURNING s.*",
            7,
        ),
        SessionStatement.GET_MESSAGE: (
            "SELECT * FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND session_id=%s AND id=%s::bigint",
            2,
        ),
        SessionStatement.MESSAGE_PARENTS: (
            "SELECT id,parent_message_id FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND session_id=%s ORDER BY id",
            1,
        ),
        SessionStatement.MASTERYPATH: (
            "SELECT 1 FROM enterprise.mastery_paths WHERE tenant_id=%s AND owner_id=%s AND path_id=%s",
            1,
        ),
        SessionStatement.READING_WORKSPACE: (
            "SELECT 1 FROM enterprise.reading_workspaces WHERE tenant_id=%s AND owner_id=%s AND workspace_id=%s",
            1,
        ),
        SessionStatement.READING_MATERIAL: (
            "SELECT 1 FROM enterprise.reading_materials WHERE tenant_id=%s AND owner_id=%s AND material_id=%s",
            1,
        ),
        SessionStatement.CLEAR_PREFERENCE_REFS: (
            "DELETE FROM enterprise.session_references WHERE tenant_id=%s AND owner_id=%s AND session_id=%s AND source_kind='preferences' AND source_id='' RETURNING target_id",
            1,
        ),
        SessionStatement.RECORD_PREFERENCE_REF: (
            "INSERT INTO enterprise.session_references(tenant_id,owner_id,session_id,kind,target_id,source_kind,source_id) VALUES(%s,%s,%s,%s,%s,'preferences','') ON CONFLICT DO NOTHING RETURNING target_id",
            3,
        ),
    }
)


def session_statement_contract(statement):
    if type(statement) is not SessionStatement:
        raise ValueError("only an approved SessionStatement is accepted; SQL text is forbidden")
    return _SESSION_STATEMENTS[statement]
