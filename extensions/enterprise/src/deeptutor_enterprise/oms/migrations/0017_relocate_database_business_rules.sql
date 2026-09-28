-- Relocate OMS business routines, triggers, and CHECK rules to application code.

DROP TRIGGER IF EXISTS guard_school_binding_version ON oms.school_bindings;
DROP FUNCTION IF EXISTS oms.guard_school_binding_version();

ALTER TABLE oms."attempt_evidence_events" DROP CONSTRAINT IF EXISTS "attempt_evidence_events_event_kind_check";
ALTER TABLE oms."audit_events" DROP CONSTRAINT IF EXISTS "audit_events_result_check";
ALTER TABLE oms."grant_commands" DROP CONSTRAINT IF EXISTS "grant_commands_result_check";
ALTER TABLE oms."quota_grants" DROP CONSTRAINT IF EXISTS "quota_grants_acquisition_method_check";
ALTER TABLE oms."quota_grants" DROP CONSTRAINT IF EXISTS "quota_grants_status_check";
ALTER TABLE oms."school_bindings" DROP CONSTRAINT IF EXISTS "school_bindings_check";
ALTER TABLE oms."school_bindings" DROP CONSTRAINT IF EXISTS "school_bindings_status_check";
ALTER TABLE oms."service_definitions" DROP CONSTRAINT IF EXISTS "service_definitions_resource_category_check";
ALTER TABLE oms."supply_lots" DROP CONSTRAINT IF EXISTS "supply_lots_status_check";
ALTER TABLE oms."supply_lots" DROP CONSTRAINT IF EXISTS "supply_lots_verified_native";
ALTER TABLE oms."tenant_service_entitlements" DROP CONSTRAINT IF EXISTS "tenant_service_entitlements_status_check";
ALTER TABLE oms."usage_attempts" DROP CONSTRAINT IF EXISTS "usage_attempts_status_check";
ALTER TABLE oms."usage_attempts" DROP CONSTRAINT IF EXISTS "usage_attempts_subject_kind_check";
