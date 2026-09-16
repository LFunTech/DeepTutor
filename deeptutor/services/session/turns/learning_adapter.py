"""Generated behavior slice of the unified turn runtime."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.trace import build_trace_metadata
from deeptutor.learning.runtime import get_learning_runtime
from deeptutor.learning.service import LearningService

if TYPE_CHECKING:
    from deeptutor.services.session.protocol import SessionStoreProtocol

    from .._turn_runtime_shared import _TurnExecution


logger = logging.getLogger(__name__)


class LearningTurnAdapter:
    if TYPE_CHECKING:
        store: SessionStoreProtocol
        _lock: asyncio.Lock
        _executions: dict[str, _TurnExecution]

        async def _publish_live_event(
            self,
            execution: _TurnExecution,
            event: StreamEvent,
        ) -> dict[str, Any]: ...

        async def cancel_turn(self, turn_id: str) -> bool: ...

    async def _is_awaiting_user_reply(self, turn_id: str) -> bool:
        async with self._lock:
            execution = self._executions.get(turn_id)
            return execution is not None and execution.awaiting_user_reply

    async def _release_superseded_lease(self, path_id, lease):
        # 未知旧进程绝不依据TTL或“本进程没task”抢占；只有本进程真实等待者可取消。
        if lease.kind != "turn":
            return
        if await self._is_awaiting_user_reply(lease.turn_id):
            await self.cancel_turn(lease.turn_id)

    async def _release_learning_lease(self, execution):
        runtime = execution.learning_runtime
        if runtime is None:
            raise RuntimeError("Learning execution authority is unavailable; recovery required")
        return await runtime.release_turn_lease()

    async def _commit_mastery_card_answer(
        self, *, path_id, session_id, turn_id, question_id, answer
    ):
        execution = self._executions[turn_id]
        runtime = execution.learning_runtime
        if runtime is None:
            raise RuntimeError("Learning turn authority is unavailable")

        def record(unit):
            from deeptutor.learning.service import StaleInteractionError

            active = unit.get_active_interaction(path_id)
            if active is None or active.interaction_id != question_id:
                raise StaleInteractionError(question_id, active.interaction_id if active else "")
            return LearningService(unit).record_question_answer(
                path_id, answer, interaction_id=question_id, session_id=session_id, turn_id=turn_id
            )

        await runtime.run(record)

    async def _grade_submitted_card_answer(
        self,
        execution: _TurnExecution,
        *,
        path_id: str,
        answer: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Rule on a card answer now, before the tutor writes a word.

        Everything the card needs to show a verdict is already server-side:
        the expected label and the explanation were registered when the
        question was posed. Waiting for the tutor to call ``mastery_grade``
        left the learner looking at their own pick for as long as a full LLM
        round took — half a minute, for a ruling that takes milliseconds and
        was never the model's to make.

        The verdict is published as the ``mastery_grade`` tool result the card
        already reads, so it renders with no client change and persists with
        the turn (a reload still shows it). The tutor's own grade call later in
        the turn replays the same committed attempt rather than scoring twice.

        Best-effort: an answer that cannot be graded — a stale card, an
        unreadable pick — leaves the interaction as it was for the tutor to
        sort out, and never sinks the turn.
        """
        question_id = str((answer or {}).get("question_id") or "").strip()
        text = str((answer or {}).get("text") or "")
        if not path_id or not question_id or not text:
            return None
        # Grading is one deterministic engine operation and this tool is its
        # only entry point; calling it here keeps that logic in one place
        # rather than growing a second copy on the runtime side.
        from deeptutor.capabilities.mastery.tools import MasteryGradeTool

        result = await MasteryGradeTool().execute(
            _mastery_path_id=path_id,
            _session_id=execution.session_id,
            _turn_id=execution.turn_id,
            question_id=question_id,
            answer=text,
        )
        payload = (result.metadata or {}).get("mastery_grade")
        if not result.success or not isinstance(payload, dict):
            return None
        # One complete trace group, the same shape the dispatcher emits for a
        # tool the model called: a lone result with no terminal status renders
        # as a row that never stops running.
        call_id = f"mastery-grade-{execution.turn_id}-{question_id}"
        trace_meta = build_trace_metadata(
            call_id=call_id,
            phase="grading",
            label="Mastery Grade",
            call_kind="tool_call",
            trace_id=call_id,
            tool="mastery_grade",
        )
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.TOOL_RESULT,
                source="mastery",
                stage="grading",
                content=result.content,
                metadata={
                    **trace_meta,
                    "trace_kind": "tool_result",
                    "tool_metadata": {"mastery_grade": payload},
                },
            ),
        )
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.PROGRESS,
                source="mastery",
                stage="grading",
                content="",
                metadata={
                    **trace_meta,
                    "trace_kind": "call_status",
                    "call_state": "complete",
                },
            ),
        )
        return payload

    async def _skip_card_question(
        self,
        execution: _TurnExecution,
        *,
        path_id: str,
        skip: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Drop the question the learner declined, before the tutor starts.

        A posed question ends its turn and stays open on the path, so a learner
        who does not want to answer it had no way past it: the engine holds one
        open question, and the tutor's next ``mastery_quiz`` simply re-presents
        the same card. Abandoning it here — the same place a card answer is
        graded — means the tutor's first ``mastery_status`` already sees a path
        with nothing pending, and can move on without being told to.

        Scoped to the question the card named: by the time this runs, an open
        question that is *not* the one on the learner's card is one they never
        declined.

        Best-effort, like grading: a stale card must not sink the turn.
        """
        question_id = str((skip or {}).get("question_id") or "").strip()
        if not path_id or not question_id:
            return None
        from deeptutor.capabilities.mastery.tools import MasterySkipQuestionTool

        runtime = get_learning_runtime()
        active = await runtime.run(lambda u: u.get_active_interaction(path_id))
        if active is None or active.interaction_id != question_id:
            return None
        result = await MasterySkipQuestionTool().execute(
            _mastery_path_id=path_id, _session_id=execution.session_id, _turn_id=execution.turn_id
        )
        payload = (result.metadata or {}).get("mastery_skip_question")
        if not result.success or not isinstance(payload, dict):
            return None
        # The tool reports the interaction it dropped; the card matches on the
        # id it was posed with, which is the same value. Stated explicitly so
        # the card can find its own verdict without trusting that.
        payload = {**payload, "question_id": question_id}
        call_id = f"mastery-skip-{execution.turn_id}-{question_id}"
        trace_meta = build_trace_metadata(
            call_id=call_id,
            phase="grading",
            label="Mastery Skip",
            call_kind="tool_call",
            trace_id=call_id,
            tool="mastery_skip_question",
        )
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.TOOL_RESULT,
                source="mastery",
                stage="grading",
                content=result.content,
                metadata={
                    **trace_meta,
                    "trace_kind": "tool_result",
                    "tool_metadata": {"mastery_skip_question": payload},
                },
            ),
        )
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.PROGRESS,
                source="mastery",
                stage="grading",
                content="",
                metadata={
                    **trace_meta,
                    "trace_kind": "call_status",
                    "call_state": "complete",
                },
            ),
        )
        return payload

    async def _acquire_mastery_path_lease(
        self,
        *,
        path_id: str,
        session_id: str,
        turn_id: str,
        owns_path: bool,
    ) -> None:
        """Bind a session to its path and take over from any superseded turn."""
        from deeptutor.learning.contracts import PathLeaseConflictError

        runtime = await get_learning_runtime().for_turn(session_id, turn_id)
        execution = self._executions[turn_id]
        execution.learning_runtime = runtime
        lease = await runtime.run(lambda u: u.get_path_lease(path_id))
        if lease is not None and lease.turn_id != turn_id:
            await self._release_superseded_lease(path_id, lease)

        def acquire(unit):
            unit.acquire_path_lease(path_id, session_id, turn_id)
            unit.bind_session(path_id, session_id, owns_path=owns_path)

        try:
            try:
                await runtime.run(acquire)
            except BaseException:
                await runtime.release_turn_lease()
                raise
        except PathLeaseConflictError as exc:
            raise RuntimeError("mastery_path_busy: path has an active execution") from exc

    @staticmethod
    async def _validate_mastery_session_topic(
        *,
        session_id: str,
        requested_path_id: str,
        remembered_path_id: str,
    ) -> None:
        """Reject a topic URL paired with a conversation held on another path.

        A conversation is on exactly one path, so this is a comparison against
        one value: the membership the store holds, or — for a conversation
        that predates memberships — the path remembered on the session. A
        conversation with neither is new and may start anywhere.

        An in-chat ``mastery_switch`` moves the membership itself, so a
        legitimate move is never seen here as a mismatch.
        """

        current = await get_learning_runtime().run(lambda u: u.path_id_for_session(session_id))
        expected = current or str(remembered_path_id or "").strip()
        if expected and requested_path_id != expected:
            raise RuntimeError(
                "mastery_session_topic_mismatch: "
                f"session {session_id!r} is on path {expected!r}, not {requested_path_id!r}"
            )
