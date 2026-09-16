"""有界稳定游标查询；兼容 list 超限显式报错，不全历史 fetchall。"""

import base64
import hashlib
import json
import math

from deeptutor.learning.contracts import (
    _ACTIVE_INTERACTION_STATES,
    LearningPage,
    LearningPaginationRequired,
)
from deeptutor.learning.models import MasteryEvent, MasteryTopic, TopicMetadata, TopicSource

from .base import validate_id
from .transaction import interaction_from_row

COMPAT_LIMIT = 1000
PAGE_LIMIT = 200


class LearningQueries:
    @staticmethod
    def _default_map_seed(path):
        return int.from_bytes(hashlib.sha256(path.encode()).digest()[:4], "big")

    def _cursor(self, kind, key):
        return base64.urlsafe_b64encode(
            json.dumps([1, self.event_scope, kind, key], separators=(",", ":")).encode()
        ).decode()

    def _decode(self, cursor, kind):
        try:
            if not isinstance(cursor, str) or len(cursor) > 4096:
                raise ValueError()
            version, scope, actual, key = json.loads(
                base64.b64decode(cursor, altchars=b"-_", validate=True)
            )
            if version != 1 or scope != self.event_scope or kind != actual:
                raise ValueError()
            if kind == "paths":
                if not isinstance(key, str):
                    raise ValueError()
            elif not isinstance(key, list) or len(key) != 2:
                raise ValueError()
            elif kind.startswith("events:"):
                if any(type(v) is not int or v < 0 for v in key):
                    raise ValueError()
            elif (
                type(key[0]) not in (int, float)
                or not math.isfinite(key[0])
                or not isinstance(key[1], str)
            ):
                raise ValueError()
            return key
        except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
            raise ValueError("invalid learning cursor or scope") from exc

    @staticmethod
    def _limit(limit):
        return min(PAGE_LIMIT, max(1, int(limit)))

    @staticmethod
    def _compat(items):
        if len(items) > COMPAT_LIMIT:
            raise LearningPaginationRequired(
                "more than 1000 results; use bounded page/iterator API"
            )
        return items

    def list_event_page(self, path_id, *, cursor=None, after_revision=0, limit=200):
        path = validate_id(path_id)
        kind = f"events:{path}"
        limit = self._limit(limit)
        with self._unit() as u:
            if cursor is None:
                predicate, params = "revision>%s", (max(0, int(after_revision)),)
            else:
                revision, event_id = self._decode(cursor, kind)
                if (
                    type(revision) is not int
                    or type(event_id) is not int
                    or revision < 0
                    or event_id < 0
                ):
                    raise ValueError("invalid learning cursor")
                predicate, params = "(revision,id)>(%s,%s)", (revision, event_id)
            rows = u._execute(
                f"SELECT * FROM enterprise.mastery_events WHERE tenant_id=%s AND owner_id=%s AND path_id=%s AND {predicate} ORDER BY revision,id LIMIT %s",
                (*u._owner, path, *params, limit + 1),
            ).fetchall()
            more = len(rows) > limit
            items = [MasteryEvent.model_validate(row) for row in rows[:limit]]
            return LearningPage(
                items, u._cursor(kind, [items[-1].revision, items[-1].id]) if more else None
            )

    def iter_events(self, path_id, *, after_revision=0):
        cursor = None
        while True:
            page = self.list_event_page(path_id, after_revision=after_revision, cursor=cursor)
            yield from page.items
            cursor = page.next_cursor
            if cursor is None:
                break

    def list_events(self, path_id, *, after_revision=0):
        items = []
        for event in self.iter_events(path_id, after_revision=after_revision):
            items.append(event)
            self._compat(items)
        return items

    def get_interaction(self, path_id, interaction_id):
        path = validate_id(path_id)
        with self._unit() as u:
            return interaction_from_row(
                u._execute(
                    "SELECT * FROM enterprise.mastery_interactions WHERE tenant_id=%s AND owner_id=%s AND path_id=%s AND interaction_id=%s",
                    (*u._owner, path, interaction_id),
                ).fetchone()
            )

    def get_active_interaction(self, path_id):
        path = validate_id(path_id)
        with self._unit() as u:
            return interaction_from_row(
                u._execute(
                    "SELECT * FROM enterprise.mastery_interactions WHERE tenant_id=%s AND owner_id=%s AND path_id=%s AND status=ANY(%s) LIMIT 1",
                    (*u._owner, path, list(_ACTIVE_INTERACTION_STATES)),
                ).fetchone()
            )

    def list_interactions(self, path_id, *, limit=200):
        path = validate_id(path_id)
        with self._unit() as u:
            rows = u._execute(
                "SELECT * FROM enterprise.mastery_interactions WHERE tenant_id=%s AND owner_id=%s AND path_id=%s ORDER BY created_at DESC,interaction_id DESC LIMIT %s",
                (*u._owner, path, min(COMPAT_LIMIT + 1, max(1, int(limit)))),
            ).fetchall()
            return [interaction_from_row(row) for row in self._compat(rows)]

    def list_path_page(self, *, cursor=None, limit=200):
        limit = self._limit(limit)
        with self._unit() as u:
            key = self._decode(cursor, "paths") if cursor else ""
            if not isinstance(key, str):
                raise ValueError("invalid learning cursor")
            rows = u._execute(
                "SELECT path_id FROM enterprise.mastery_paths WHERE tenant_id=%s AND owner_id=%s AND path_id>%s ORDER BY path_id LIMIT %s",
                (*u._owner, key, limit + 1),
            ).fetchall()
            items = [row["path_id"] for row in rows[:limit]]
            return LearningPage(items, u._cursor("paths", items[-1]) if len(rows) > limit else None)

    def list_session_page(self, path_id, *, cursor=None, limit=200):
        path = validate_id(path_id)
        kind = f"sessions:{path}"
        limit = self._limit(limit)
        with self._unit() as u:
            extra, params = "", ()
            if cursor:
                at, key = self._decode(cursor, kind)
                if not isinstance(at, (int, float)) or not isinstance(key, str):
                    raise ValueError("invalid learning cursor")
                extra, params = " AND (last_seen_at,session_id)<(%s,%s)", (at, key)
            rows = u._execute(
                f"SELECT session_id,last_seen_at FROM enterprise.mastery_path_sessions WHERE tenant_id=%s AND owner_id=%s AND path_id=%s{extra} ORDER BY last_seen_at DESC,session_id DESC LIMIT %s",
                (*u._owner, path, *params, limit + 1),
            ).fetchall()
            selected = rows[:limit]
            return LearningPage(
                [r["session_id"] for r in selected],
                u._cursor(kind, [selected[-1]["last_seen_at"], selected[-1]["session_id"]])
                if len(rows) > limit
                else None,
            )

    def list_interaction_page(self, path_id, *, cursor=None, limit=200):
        path = validate_id(path_id)
        kind = f"interactions:{path}"
        limit = self._limit(limit)
        with self._unit() as u:
            extra, params = "", ()
            if cursor:
                at, key = self._decode(cursor, kind)
                if not isinstance(at, (int, float)) or not isinstance(key, str):
                    raise ValueError("invalid learning cursor")
                extra, params = " AND (created_at,interaction_id)<(%s,%s)", (at, key)
            rows = u._execute(
                f"SELECT * FROM enterprise.mastery_interactions WHERE tenant_id=%s AND owner_id=%s AND path_id=%s{extra} ORDER BY created_at DESC,interaction_id DESC LIMIT %s",
                (*u._owner, path, *params, limit + 1),
            ).fetchall()
            selected = rows[:limit]
            return LearningPage(
                [interaction_from_row(r) for r in selected],
                u._cursor(kind, [selected[-1]["created_at"], selected[-1]["interaction_id"]])
                if len(rows) > limit
                else None,
            )

    def list_all(self):
        with self._unit() as u:
            rows = u._execute(
                "SELECT path_id FROM enterprise.mastery_paths WHERE tenant_id=%s AND owner_id=%s ORDER BY path_id LIMIT %s",
                (*u._owner, COMPAT_LIMIT + 1),
            ).fetchall()
            return self._compat([row["path_id"] for row in rows])

    def _topic(self, progress, meta, sources):
        metadata = (
            TopicMetadata.model_validate(meta)
            if meta
            else TopicMetadata(
                path_id=progress.book_id,
                map_seed=self._default_map_seed(progress.book_id),
                created_at=progress.created_at,
                updated_at=progress.updated_at,
            )
        )
        return MasteryTopic(
            metadata=metadata,
            sources=[
                TopicSource(
                    id=row["id"],
                    kind=row["kind"],
                    source_id=row["external_id"],
                    label=row["label"],
                    excerpt=row["excerpt"],
                    position=row["position"],
                    available=row["available"],
                    metadata=row["metadata"],
                    created_at=row["created_at"],
                )
                for row in sources
            ],
        )

    def _topic_rows(self, *, path=None, status="active", after=None, limit=1):
        # 一个语句共享同一 MVCC 快照。先限制路径，再关联每路径有界 sources；
        # 不升级共享事务隔离，也不取得会与后续写入 owner 锁反转的读取行锁。
        if path is not None:
            predicate, params = "p.path_id=%s", (path,)
        else:
            predicate, params = ("m.status=%s", (status,)) if status else ("TRUE", ())
            if after is not None:
                predicate += " AND (p.updated_at,p.path_id)<(%s,%s)"
                params += tuple(after)
        return self._execute(
            f"""WITH selected AS MATERIALIZED (
                SELECT p.*,to_jsonb(m) AS topic_metadata
                FROM enterprise.mastery_paths p
                LEFT JOIN enterprise.mastery_topic_meta m USING(tenant_id,owner_id,path_id)
                WHERE p.tenant_id=%s AND p.owner_id=%s AND {predicate}
                ORDER BY p.updated_at DESC,p.path_id DESC LIMIT %s
            )
            SELECT p.*, sources.items AS topic_sources, memberships.n AS session_count,
                   active.item AS active_interaction
            FROM selected p
            CROSS JOIN LATERAL (
                SELECT COALESCE(jsonb_agg(s ORDER BY s.position,s.created_at,s.id),'[]'::jsonb) items
                FROM (
                    SELECT s.* FROM enterprise.mastery_topic_sources s
                    WHERE s.tenant_id=p.tenant_id AND s.owner_id=p.owner_id AND s.path_id=p.path_id
                    ORDER BY s.position,s.created_at,s.id LIMIT {COMPAT_LIMIT + 1}
                ) s
            ) sources
            CROSS JOIN LATERAL (
                SELECT count(*) n FROM enterprise.mastery_path_sessions b
                WHERE b.tenant_id=p.tenant_id AND b.owner_id=p.owner_id AND b.path_id=p.path_id
            ) memberships
            LEFT JOIN LATERAL (
                SELECT to_jsonb(i) item FROM enterprise.mastery_interactions i
                WHERE i.tenant_id=p.tenant_id AND i.owner_id=p.owner_id AND i.path_id=p.path_id
                  AND i.status=ANY(%s) LIMIT 1
            ) active ON true
            ORDER BY p.updated_at DESC,p.path_id DESC""",
            (*self._owner, *params, limit, list(_ACTIVE_INTERACTION_STATES)),
        ).fetchall()

    def get_topic_snapshot(self, path_id):
        """一个已提交 SQL snapshot 中的路径、来源、membership count、active interaction。"""
        with self._unit() as u:
            rows = u._topic_rows(path=validate_id(path_id))
            if not rows:
                return None
            row = rows[0]
            progress = u._progress(row)
            return (
                progress,
                u._topic(progress, row["topic_metadata"], u._compat(row["topic_sources"])),
                row["session_count"],
                interaction_from_row(row["active_interaction"]),
            )

    def get_topic(self, path_id, *, progress=None):
        path = validate_id(path_id)
        if progress is not None and progress.book_id != path:
            raise ValueError("progress does not belong to the requested topic")
        with self._unit() as u:
            # 传入 DTO 不作为当前资源授权、存在性或快照版本的证明。
            rows = u._topic_rows(path=path)
            if not rows:
                return None
            row = rows[0]
            return u._topic(
                u._progress(row), row["topic_metadata"], self._compat(row["topic_sources"])
            )

    def put_topic(self, metadata, sources):
        with self._unit(write=True) as u:
            with u.transaction(metadata.path_id) as tx:
                tx.put_topic(metadata, sources)
            return u.get_topic(metadata.path_id)

    def has_active_topics(self):
        with self._unit() as u:
            return (
                u._execute(
                    "SELECT 1 FROM enterprise.mastery_topic_meta WHERE tenant_id=%s AND owner_id=%s AND status='active' LIMIT 1",
                    u._owner,
                ).fetchone()
                is not None
            )

    def list_topic_page(self, *, status="active", cursor=None, limit=200):
        limit = self._limit(limit)
        kind = f"topics:{status}"
        with self._unit() as u:
            after = self._decode(cursor, kind) if cursor is not None else None
            rows = u._topic_rows(status=status, after=after, limit=limit + 1)
            more, rows = len(rows) > limit, rows[:limit]
            items = []
            for row in rows:
                progress = u._progress(row)
                items.append(
                    (
                        progress,
                        u._topic(
                            progress, row["topic_metadata"], self._compat(row["topic_sources"])
                        ),
                        row["session_count"],
                        interaction_from_row(row["active_interaction"]),
                    )
                )
            return LearningPage(
                items,
                u._cursor(kind, [rows[-1]["updated_at"], rows[-1]["path_id"]]) if more else None,
            )

    def other_built_path_cardinality(self, path_id):
        """只区分没有/一个/多个，不把完整页误当全量列表。"""
        with self._unit() as unit:
            rows = unit._execute(
                "SELECT DISTINCT path_id FROM enterprise.mastery_knowledge_points "
                "WHERE tenant_id=%s AND owner_id=%s AND active AND path_id<>%s LIMIT 2",
                (*unit._owner, validate_id(path_id)),
            ).fetchall()
            return len(rows)

    def iter_topic_snapshots(self, *, status="active"):
        cursor = None
        while True:
            page = self.list_topic_page(status=status, cursor=cursor)
            yield from page.items
            cursor = page.next_cursor
            if cursor is None:
                break

    def list_topic_snapshots(self, *, status="active"):
        items = []
        for item in self.iter_topic_snapshots(status=status):
            items.append(item)
            self._compat(items)
        return items
