-- 学校权威绑定不可删除后重建以复活旧授权；改指向/状态/核验证据须推进版本。
CREATE FUNCTION oms.guard_school_binding_version() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE material_change boolean;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'school binding must be revoked, not deleted'
      USING ERRCODE='23514';
  END IF;
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
    RAISE EXCEPTION 'school binding tenant cannot change'
      USING ERRCODE='23514';
  END IF;
  material_change :=
    (NEW.eduplus_tenant_id,NEW.status,NEW.verified_at,NEW.verified_by,NEW.source_ref)
    IS DISTINCT FROM
    (OLD.eduplus_tenant_id,OLD.status,OLD.verified_at,OLD.verified_by,OLD.source_ref);
  IF (material_change AND NEW.version<>OLD.version+1)
     OR (NOT material_change AND NEW.version<>OLD.version) THEN
    RAISE EXCEPTION 'school binding version must follow authority change'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_school_binding_version BEFORE UPDATE OR DELETE
  ON oms.school_bindings FOR EACH ROW
  EXECUTE FUNCTION oms.guard_school_binding_version();
