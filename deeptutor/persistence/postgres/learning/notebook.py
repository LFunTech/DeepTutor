"""教学聚合与题库的同连接原子边界；不调用异步Store/不开第二事务。"""

import time

from deeptutor.persistence.postgres.notebook_upsert import (
    UPSERT_SQL,
    mastery_reference_query,
    prepare_upsert,
    require_mastery_reference,
)


class LearningNotebook:
    def upsert_mastery_notebook_entries(self, session_id, items):
        with self._unit(write=True) as u:
            if u._open_path is None:
                raise RuntimeError("mastery notebook writes require an open learning transaction")
            path = u._open_path
            u._authority()
            u._assert_path_write(path)
            lease = u._lease(path)
            if lease is None or not u._owns(lease):
                raise RuntimeError("mastery notebook writes require current path lease")
            if lease.kind == "turn" and session_id != lease.session_id:
                raise ValueError("notebook session must match current turn authority")
            u._check_session_reference(session_id)
            # 当前聚合可在本事务刚新增KP；同步最小投影后，来源FK和所有正文同生共死。
            if not items:
                return 0
            u._current_tx.touch()
            u._sync_points(u._current_tx.progress)
            now = time.time()
            count = 0
            for item in items:
                if (
                    item.get("source") != "mastery_path"
                    or str(item.get("material_id") or "") != path
                ):
                    raise ValueError("notebook source must be mastery_path and match current path")
                if lease.kind == "turn" and str(item.get("turn_id") or "") != lease.turn_id:
                    raise ValueError("notebook execution turn must match current turn authority")
                prepared = prepare_upsert(u._owner, session_id, item, now)
                if prepared is None:
                    continue
                require_mastery_reference(
                    u._execute(*mastery_reference_query(u._owner, session_id, item)).fetchone()
                )
                u._execute(UPSERT_SQL, prepared[1])
                count += 1
            return count
