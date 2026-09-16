"""锁定学习聚合内的交互、来源、事件；不创建/提交数据库事务。"""

from copy import deepcopy
import time

import psycopg

from deeptutor.learning.contracts import (
    _ACTIVE_INTERACTION_STATES,
    _ALLOWED_INTERACTION_TRANSITIONS,
    LearningReferenceError,
    LearningStoreError,
)
from deeptutor.learning.models import InteractionStatus, MasteryInteraction
from deeptutor.persistence.postgres._ownership import Lease

from .base import jsonb, redact


def interaction_from_row(row):
    return MasteryInteraction.model_validate(row) if row else None


class LearningTransaction:
    def __init__(self, unit, progress, *, created):
        self._unit = unit
        self._lease = Lease()
        self.progress = progress
        self.base_revision = progress.version
        self.changed = created
        self._events = []
        if created:
            self.emit("path.created")

    def _check(self):
        self._lease.check()
        self._unit._check()

    def touch(self):
        self._check()
        self.changed = True

    def emit(self, event_type, payload=None, *, session_id="", turn_id=""):
        self._check()
        self._unit._check_session_reference(session_id)
        name = str(event_type or "").strip()
        if not name:
            self._unit._failed = True
            raise ValueError("event_type must not be empty")
        self._events.append(
            (name, redact(dict(payload or {})), str(session_id or ""), str(turn_id or ""))
        )
        self.changed = True

    @property
    def events(self):
        self._check()
        return deepcopy(self._events)

    def get_interaction(self, interaction_id):
        self._check()
        return self._unit.get_interaction(self.progress.book_id, interaction_id)

    def active_interaction(self):
        self._check()
        return self._unit.get_active_interaction(self.progress.book_id)

    def put_interaction(self, interaction):
        self._check()
        u = self._unit
        try:
            if interaction.path_id != self.progress.book_id:
                raise ValueError("interaction path_id does not match transaction path")
            existing = u._execute(
                "SELECT * FROM enterprise.mastery_interactions WHERE tenant_id=%s AND owner_id=%s AND interaction_id=%s",
                (*u._owner, interaction.interaction_id),
            ).fetchone()
            if existing:
                if existing["path_id"] != interaction.path_id:
                    raise ValueError("interaction already belongs to another path")
                current = InteractionStatus(existing["status"])
                if interaction.status not in _ALLOWED_INTERACTION_TRANSITIONS[current]:
                    raise LearningStoreError(
                        f"Invalid mastery interaction transition: {current.value} -> {interaction.status.value}"
                    )
                if any(
                    existing["question"].get(key, "") != getattr(interaction.question, key)
                    for key in ("question_id", "knowledge_point_id", "module_id")
                ):
                    raise LearningStoreError("persisted question provenance is immutable")
                # Service可为旧choice补回选项正文/答案；重复出题仍由Service返回已有交互。
            else:
                ids = {kp.id for module in self.progress.modules for kp in module.knowledge_points}
                if interaction.question.knowledge_point_id not in ids:
                    raise LearningReferenceError(
                        "new interaction requires an active knowledge point"
                    )
            if (
                existing is None
                or existing["session_id"] != interaction.session_id
                or existing["turn_id"] != interaction.turn_id
            ):
                u._check_session_reference(interaction.session_id)
            now = time.time()
            u._execute(
                """INSERT INTO enterprise.mastery_interactions
                (tenant_id,owner_id,path_id,interaction_id,status,question,session_id,turn_id,user_answer,result,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(tenant_id,owner_id,interaction_id) DO UPDATE SET
                status=EXCLUDED.status,question=EXCLUDED.question,session_id=EXCLUDED.session_id,turn_id=EXCLUDED.turn_id,
                user_answer=EXCLUDED.user_answer,result=EXCLUDED.result,updated_at=EXCLUDED.updated_at""",
                (
                    *u._owner,
                    interaction.path_id,
                    interaction.interaction_id,
                    interaction.status.value,
                    jsonb(interaction.question.model_dump(mode="json")),
                    interaction.session_id,
                    interaction.turn_id,
                    interaction.user_answer,
                    jsonb(interaction.result),
                    interaction.created_at,
                    now,
                ),
            )
            self.touch()
        except psycopg.errors.UniqueViolation as exc:
            u._failed = True
            raise LearningStoreError("path already has an active interaction") from exc
        except BaseException:
            u._failed = True
            raise

    def abandon_active_interactions(self):
        self._check()
        u = self._unit
        result = u._execute(
            "UPDATE enterprise.mastery_interactions SET status=%s,updated_at=%s WHERE tenant_id=%s AND owner_id=%s AND path_id=%s AND status=ANY(%s)",
            (
                "abandoned",
                time.time(),
                *u._owner,
                self.progress.book_id,
                list(_ACTIVE_INTERACTION_STATES),
            ),
        )
        if result.rowcount:
            self.touch()
        return result.rowcount

    def put_topic(self, metadata, sources):
        self._check()
        u = self._unit
        try:
            if metadata.path_id != self.progress.book_id:
                raise ValueError("topic metadata path_id does not match transaction path")
            now = time.time()
            u._execute(
                """INSERT INTO enterprise.mastery_topic_meta
                (tenant_id,owner_id,path_id,goal,description,emoji,map_seed,status,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(tenant_id,owner_id,path_id) DO UPDATE SET goal=EXCLUDED.goal,
                description=EXCLUDED.description,emoji=EXCLUDED.emoji,map_seed=EXCLUDED.map_seed,
                status=EXCLUDED.status,updated_at=EXCLUDED.updated_at""",
                (
                    *u._owner,
                    metadata.path_id,
                    metadata.goal,
                    metadata.description,
                    metadata.emoji,
                    metadata.map_seed or u._default_map_seed(metadata.path_id),
                    metadata.status,
                    metadata.created_at,
                    now,
                ),
            )
            if len(sources) > 1000:
                raise ValueError("a topic supports at most 1000 sources")
            u._execute(
                "DELETE FROM enterprise.mastery_topic_sources WHERE tenant_id=%s AND owner_id=%s AND path_id=%s",
                (*u._owner, metadata.path_id),
            )
            for position, source in enumerate(sorted(sources, key=lambda item: item.position)):
                if source.kind.value == "chat" and not source.source_id.startswith("partner:"):
                    u._check_session_reference(source.source_id)
                if source.kind.value == "question_bank":
                    entry = u._execute(
                        "SELECT session_id FROM enterprise.notebook_entries WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                        (*u._owner, int(source.source_id)),
                    ).fetchone()
                    if entry is None:
                        raise LearningReferenceError("question-bank source unavailable")
                    u._check_session_reference(entry["session_id"])
                u._execute(
                    """INSERT INTO enterprise.mastery_topic_sources
                  (tenant_id,owner_id,path_id,id,kind,external_id,label,excerpt,position,available,metadata,created_at)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        *u._owner,
                        metadata.path_id,
                        source.id,
                        source.kind.value,
                        source.source_id,
                        source.label,
                        source.excerpt,
                        position,
                        source.available,
                        jsonb(source.metadata),
                        source.created_at,
                    ),
                )
            self.touch()
        except BaseException:
            u._failed = True
            raise
