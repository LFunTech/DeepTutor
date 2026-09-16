"""Learning来源使用真实资源provider，字符串及旧文件路径从不代表授权。"""

from deeptutor.learning.models import TopicSourceKind
from deeptutor.learning.runtime import LearningProviderUnavailable


async def authorize_sources(runtime, sources):
    await runtime.authorize()
    for source in sources:
        if source.kind == TopicSourceKind.GOAL:
            continue
        if source.kind == TopicSourceKind.CHAT and not source.source_id.startswith("partner:"):
            if await runtime.session_store.get_session(source.source_id) is None:
                raise PermissionError("Source session is unavailable")
        elif source.kind == TopicSourceKind.QUESTION_BANK:
            try:
                entry_id = int(source.source_id)
            except ValueError:
                raise PermissionError("Invalid question-bank source") from None
            if await runtime.session_store.get_notebook_entry(entry_id) is None:
                raise PermissionError("Question-bank source is unavailable")
        else:
            if runtime.source_provider is None:
                raise LearningProviderUnavailable(
                    f"PostgreSQL {source.kind.value} source authority provider is not configured"
                )
            await runtime.source_provider.authorize(runtime.scope, source)
    await runtime.authorize()


async def ground_sources(runtime, sources, *, name="", goal=""):
    await authorize_sources(runtime, sources)
    result = []
    for source in sources:
        item = source.model_copy(deep=True)
        if source.kind == TopicSourceKind.GOAL:
            pass
        elif source.kind == TopicSourceKind.CHAT and not source.source_id.startswith("partner:"):
            messages = await runtime.session_store.get_messages_for_context(source.source_id)
            item.excerpt = "\n".join(str(row.get("content") or "") for row in messages[-20:])[
                :12000
            ]
        elif source.kind == TopicSourceKind.QUESTION_BANK:
            row = await runtime.session_store.get_notebook_entry(int(source.source_id))
            if row is None:
                raise PermissionError("Question-bank source is unavailable")
            item.excerpt = str(row.get("question") or "")[:12000]
        else:
            item = await runtime.source_provider.ground(runtime.scope, item, name=name, goal=goal)
        result.append(item)
    await runtime.authorize()
    return result


async def topic_materials(runtime, sources):
    from deeptutor.learning.topic_materials import (
        TopicMaterial,
        TopicMaterials,
        render_topic_manifest,
    )

    await authorize_sources(runtime, sources)
    external = [
        s
        for s in sources
        if s.kind not in (TopicSourceKind.GOAL, TopicSourceKind.CHAT, TopicSourceKind.QUESTION_BANK)
        or (s.kind == TopicSourceKind.CHAT and s.source_id.startswith("partner:"))
    ]
    if external:
        # BOOK按章、FILE为KB文件等原语义交由真实资源provider，绝不映射为readingID。
        materials = await runtime.source_provider.materials(runtime.scope, sources)
    else:
        grounded = await ground_sources(runtime, sources)
        materials = TopicMaterials(
            materials=[
                TopicMaterial(
                    sid=f"topic:{s.id}" if s.excerpt and s.available else "",
                    kind=s.kind.value,
                    name=s.label,
                    full_text=s.excerpt if s.available else "",
                    available=s.available,
                )
                for s in grounded
            ]
        )
    await runtime.authorize()
    return render_topic_manifest(materials)
