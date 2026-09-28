-- 首管 actor 候选由应用事务内 FOR UPDATE 与条件更新保证终态不可复活。
DROP TRIGGER guard_lifecycle_actor_candidate ON eduplus2.lifecycle_actor_candidates;
DROP FUNCTION eduplus2.guard_lifecycle_actor_candidate();
