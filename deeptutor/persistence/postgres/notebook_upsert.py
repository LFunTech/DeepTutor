"""题库upsert领域专用纯SQL/值构造；sync学习与async题库共用，不建立连接。"""

import json

from psycopg.types.json import Jsonb

from deeptutor.services.session.question_bank import (
    ASSESSMENT_SOURCES,
    QuestionBankReferenceConflict,
)


def _json(value):
    return Jsonb(value, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, allow_nan=False))


UPSERT_SQL = """
INSERT INTO enterprise.notebook_entries(
  tenant_id,owner_id,session_id,turn_id,question_id,question,
  question_type,options,correct_answer,explanation,difficulty,
  user_answer,user_answer_images,source,material_id,material_title,
  section_id,section_title,score_trend,is_correct,resolved,created_at,updated_at
) VALUES(
  %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
  COALESCE(%s::jsonb,'[]'::jsonb),%s,%s,%s,%s,%s,'new',%s,%s,%s,%s
)
ON CONFLICT(tenant_id,owner_id,session_id,turn_id,question_id)
DO UPDATE SET
  question=EXCLUDED.question,
  question_type=EXCLUDED.question_type,
  options=EXCLUDED.options,
  correct_answer=EXCLUDED.correct_answer,
  explanation=EXCLUDED.explanation,
  difficulty=EXCLUDED.difficulty,
  user_answer=EXCLUDED.user_answer,
  user_answer_images=CASE WHEN %s THEN EXCLUDED.user_answer_images
    ELSE notebook_entries.user_answer_images END,
  source=EXCLUDED.source,
  material_id=EXCLUDED.material_id,
  material_title=EXCLUDED.material_title,
  section_id=EXCLUDED.section_id,
  section_title=EXCLUDED.section_title,
  score_trend=CASE
    WHEN notebook_entries.is_correct=EXCLUDED.is_correct THEN 'unchanged'
    WHEN EXCLUDED.is_correct THEN 'improved' ELSE 'declined' END,
  is_correct=EXCLUDED.is_correct,
  resolved=CASE
    WHEN EXCLUDED.is_correct THEN true
    WHEN NOT EXCLUDED.is_correct AND notebook_entries.is_correct THEN false
    ELSE notebook_entries.resolved END,
  updated_at=EXCLUDED.updated_at,
  version=notebook_entries.version+1
"""


def prepare_upsert(owner, session_id, item, now):
    question = str(item.get("question") or "").strip()
    question_id = str(item.get("question_id") or "").strip()
    if not question or not question_id:
        return None
    source = str(item.get("source") or "deep_question")
    if source not in ASSESSMENT_SOURCES:
        source = "deep_question"
    images = item.get("user_answer_images")
    has_images = isinstance(images, list)
    return source, (
        *owner,
        session_id,
        str(item.get("turn_id") or "").strip(),
        question_id,
        question,
        str(item.get("question_type") or ""),
        _json(item.get("options") or {}),
        str(item.get("correct_answer") or ""),
        str(item.get("explanation") or ""),
        str(item.get("difficulty") or ""),
        str(item.get("user_answer") or ""),
        _json(images) if has_images else None,
        source,
        str(item.get("material_id") or ""),
        str(item.get("material_title") or ""),
        str(item.get("section_id") or ""),
        str(item.get("section_title") or ""),
        bool(item.get("is_correct")),
        bool(item.get("is_correct")),
        now,
        now,
        has_images,
    )


def mastery_reference_query(owner, session_id, item):
    material = str(item.get("material_id") or "")
    section = str(item.get("section_id") or "")
    sql = """SELECT
      EXISTS(SELECT 1 FROM enterprise.mastery_paths WHERE tenant_id=%s AND owner_id=%s AND path_id=%s) AS path_exists,
      (%s='' OR EXISTS(SELECT 1 FROM enterprise.mastery_knowledge_points kp
        WHERE kp.tenant_id=%s AND kp.owner_id=%s AND kp.path_id=%s AND kp.kp_id=%s
        AND (kp.active OR EXISTS(SELECT 1 FROM enterprise.notebook_entries e
          WHERE e.tenant_id=kp.tenant_id AND e.owner_id=kp.owner_id AND e.session_id=%s
          AND e.turn_id=%s AND e.question_id=%s AND e.source='mastery_path'
          AND e.material_id=kp.path_id AND e.section_id=kp.kp_id)))) AS point_available"""
    return sql, (
        *owner,
        material,
        section,
        *owner,
        material,
        section,
        session_id,
        str(item.get("turn_id") or "").strip(),
        str(item.get("question_id") or "").strip(),
    )


def require_mastery_reference(row):
    if not row["path_exists"] or not row["point_available"]:
        raise QuestionBankReferenceConflict(
            "new mastery provenance requires an active path/knowledge point"
        )


def reading_reference_query(owner, item):
    """reading 表已存在后，只接受当前 scope 中可阅读的真实材料。"""
    return (
        "SELECT EXISTS(SELECT 1 FROM enterprise.reading_materials WHERE tenant_id=%s AND owner_id=%s AND material_id=%s AND status='ready') AS available",
        (*owner, str(item.get("material_id") or "")),
    )


def require_reading_reference(row):
    if not row["available"]:
        raise QuestionBankReferenceConflict("reading provenance requires a current ready material")
