# 隔离合成 PG 现行 schema 盘点

仅用于迁移设计；不含真实学校数据。旧 SQL 历史不改写。

- 用户定义函数：7
- 应用定义触发器：8
- PG ENUM 类型：0
- 枚举型/条件枚举型 CHECK 候选：当前 120（需逐项人工确认；本轮补记阅读材料、单值 provider 与 OMS 绑定条件）

初步拆分：85 项含 `ANY(ARRAY[...])` 的值域判断；35 项不含 `ANY` 的条件/单值/物理约束。其中 `enterprise.mastery_events.mastery_events_check`、`enterprise.mastery_interactions.mastery_interactions_check` 和 `enterprise.resource_objects.resource_objects_content_hash_check` 不以枚举业务值分支，暂列非枚举物理/关联约束候选，最终处理仍须逐项审查，不能据此批量删除。独立合成 PG 的全部 385 个 CHECK 字面审计还发现 28 项 `jsonb_typeof(...)='object/array'` 物理形状约束，不计入业务枚举退役矩阵；最终 catalog 仍须复核。

## 函数

- `management.bump_principal_policy_version()`
- `management.protect_last_administrator()`
- `management.protect_last_administrator_principal()`
- `management.validate_action_catalog_change()`
- `management.validate_assignment()`
- `management.validate_delegation_policy()`
- `oms.guard_school_binding_version()`

## 触发器

- `management.action_catalog.validate_action_catalog_change`
- `management.assignments.assignment_policy_version`
- `management.assignments.protect_last_administrator`
- `management.assignments.validate_assignment`
- `management.delegation_policies.delegation_policy_version`
- `management.delegation_policies.validate_delegation_policy`
- `management.principals.protect_last_administrator_principal`
- `oms.school_bindings.guard_school_binding_version`

## ENUM 类型

- 无

## 枚举型 CHECK 候选

- `eduplus2.audit_events.audit_events_result_check` — `CHECK ((result = ANY (ARRAY['success'::text, 'denied'::text, 'replayed'::text, 'failed'::text])))`
- `eduplus2.audit_export_jobs.audit_export_jobs_format_check` — `CHECK ((format = ANY (ARRAY['jsonl'::text, 'csv'::text])))`
- `eduplus2.audit_export_jobs.audit_export_jobs_status_check` — `CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'completed'::text, 'failed'::text, 'expired'::text])))`
- `eduplus2.external_client_registrations.external_client_registrations_registered_by_surface_check` — `CHECK ((registered_by_surface = ANY (ARRAY['tms'::text, 'oms'::text, 'webhook'::text, 'ops_cli'::text, 'env_allowlist'::text, 'auto_upsert'::text, 'test_seed'::text])))`
- `eduplus2.external_client_registrations.external_client_registrations_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text, 'suspended'::text, 'pending_verification'::text])))`
- `eduplus2.external_client_registrations.external_client_registrations_provider_check` — `CHECK ((provider = 'eduplus2'::text))`
- `eduplus2.identity_bindings.identity_bindings_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'disabled'::text, 'revoked'::text])))`
- `eduplus2.identity_bindings.identity_bindings_provider_check` — `CHECK ((provider = 'eduplus2'::text))`
- `eduplus2.lifecycle_actor_candidates.lifecycle_actor_candidate_resolution_check` — `CHECK ((((status = 'pending_verification'::text) AND (resolved_at IS NULL)) OR ((status = ANY (ARRAY['consumed'::text, 'revoked'::text])) AND (resolved_at IS NOT NULL))))`
- `eduplus2.lifecycle_actor_candidates.lifecycle_actor_candidate_status_check` — `CHECK ((status = ANY (ARRAY['pending_verification'::text, 'consumed'::text, 'revoked'::text])))`
- `eduplus2.lifecycle_inbox.lifecycle_inbox_processing_status_check` — `CHECK ((processing_status = ANY (ARRAY['pending_binding'::text, 'pending_reconcile'::text, 'reconciling'::text, 'verified'::text, 'denied'::text, 'retry'::text, 'rejected'::text])))`
- `eduplus2.lifecycle_targets.lifecycle_allowed_requires_binding_version` — `CHECK (((eligibility <> 'allowed'::text) OR (binding_version > 0)))`
- `eduplus2.lifecycle_targets.lifecycle_targets_check3` — `CHECK (((eligibility <> 'allowed'::text) OR ((proof_checked_at IS NOT NULL) AND (proof_expires_at IS NOT NULL) AND (proof_expires_at > proof_checked_at) AND (length(verified_client_id) > 0))))`
- `eduplus2.lifecycle_targets.lifecycle_targets_eligibility_check` — `CHECK ((eligibility = ANY (ARRAY['unknown'::text, 'allowed'::text, 'denied'::text])))`
- `eduplus2.permission_snapshots.permission_snapshots_provider_check` — `CHECK ((provider = 'eduplus2'::text))`
- `eduplus2.profile_snapshots.profile_snapshots_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'enabled'::text, 'allowed'::text, 'disabled'::text, 'deleted'::text, 'inactive'::text, 'revoked'::text])))`
- `eduplus2.profile_snapshots.profile_snapshots_provider_check` — `CHECK ((provider = 'eduplus2'::text))`
- `eduplus2.provider_clients.provider_clients_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'rotating'::text, 'revoked'::text, 'disabled'::text])))`
- `eduplus2.revocation_events.revocation_events_processing_status_check` — `CHECK ((processing_status = ANY (ARRAY['applied'::text, 'duplicate'::text, 'ignored'::text, 'failed'::text])))`
- `eduplus2.revocation_events.revocation_events_target_kind_check` — `CHECK ((target_kind = ANY (ARRAY['user'::text, 'client'::text, 'app'::text, 'tenant'::text, 'permission'::text, 'subscription'::text])))`
- `eduplus2.revocation_state.revocation_state_check` — `CHECK (((target_kind <> 'tenant'::text) OR (length(external_tenant_id) > 0)))`
- `eduplus2.revocation_state.revocation_state_check1` — `CHECK (((target_kind <> 'user'::text) OR ((length(external_tenant_id) > 0) AND (length(external_user_id) > 0))))`
- `eduplus2.revocation_state.revocation_state_check2` — `CHECK (((target_kind <> 'client'::text) OR (length(client_id) > 0)))`
- `eduplus2.revocation_state.revocation_state_check3` — `CHECK (((target_kind <> 'app'::text) OR (length(external_app_id) > 0)))`
- `eduplus2.revocation_state.revocation_state_check4` — `CHECK (((target_kind <> 'permission'::text) OR ((length(external_tenant_id) > 0) AND (length(external_user_id) > 0) AND (length(client_id) > 0))))`
- `eduplus2.revocation_state.revocation_state_target_kind_check` — `CHECK ((target_kind = ANY (ARRAY['user'::text, 'client'::text, 'app'::text, 'tenant'::text, 'permission'::text, 'subscription'::text])))`
- `eduplus2.webhook_school_state.webhook_school_state_eligibility_check` — `CHECK ((eligibility = ANY (ARRAY['unknown'::text, 'allowed'::text, 'denied'::text])))`
- `enterprise.courses.courses_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'archived'::text])))`
- `enterprise.cron_executions.cron_executions_check1` — `CHECK ((((status = 'claimed'::text) AND (completed_at_ms IS NULL)) OR ((status <> 'claimed'::text) AND (completed_at_ms IS NOT NULL))))`
- `enterprise.cron_executions.cron_executions_status_check` — `CHECK ((status = ANY (ARRAY['claimed'::text, 'ok'::text, 'error'::text, 'skipped'::text, 'uncertain'::text])))`
- `enterprise.cron_jobs.cron_jobs_check` — `CHECK ((((schedule_kind = 'at'::text) AND (at_ms IS NOT NULL) AND (every_seconds IS NULL) AND (cron_expr IS NULL)) OR ((schedule_kind = 'every'::text) AND (at_ms IS NULL) AND (every_seconds IS NOT NULL) AND (every_seconds > 0) AND (cron_expr IS NULL)) OR ((schedule_kind = 'cron'::text) AND (at_ms IS NULL) AND (every_seconds IS NULL) AND (cron_expr IS NOT NULL) AND (length(cron_expr) > 0))))`
- `enterprise.cron_jobs.cron_jobs_last_status_check` — `CHECK (((last_status IS NULL) OR (last_status = ANY (ARRAY['ok'::text, 'error'::text, 'skipped'::text, 'uncertain'::text]))))`
- `enterprise.cron_jobs.cron_jobs_schedule_kind_check` — `CHECK ((schedule_kind = ANY (ARRAY['at'::text, 'every'::text, 'cron'::text])))`
- `enterprise.executor_state.executor_state_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'stopped'::text])))`
- `enterprise.marginnote_objects.marginnote_objects_object_type_check` — `CHECK ((object_type = ANY (ARRAY['note'::text, 'excerpt'::text, 'card'::text, 'mindmap_node'::text, 'document'::text, 'comment'::text])))`
- `enterprise.mastery_events.mastery_events_check` — `CHECK (((turn_id = ''::text) OR (session_id <> ''::text)))`
- `enterprise.mastery_interactions.mastery_interactions_check` — `CHECK (((turn_id = ''::text) OR (session_id <> ''::text)))`
- `enterprise.mastery_interactions.mastery_interactions_status_check` — `CHECK ((status = ANY (ARRAY['registered'::text, 'awaiting_input'::text, 'answered'::text, 'graded'::text, 'abandoned'::text])))`
- `enterprise.mastery_path_leases.mastery_path_leases_check` — `CHECK ((((kind = 'turn'::text) AND (session_id IS NOT NULL) AND (turn_id IS NOT NULL) AND (worker_id IS NOT NULL) AND (fencing_token IS NOT NULL) AND (operation_id IS NULL)) OR ((kind = 'operation'::text) AND (session_id IS NULL) AND (turn_id IS NULL) AND (worker_id IS NULL) AND (fencing_token IS NULL) AND (operation_id IS NOT NULL))))`
- `enterprise.mastery_path_leases.mastery_path_leases_kind_check` — `CHECK ((kind = ANY (ARRAY['turn'::text, 'operation'::text])))`
- `enterprise.mastery_path_operations.mastery_path_operations_check1` — `CHECK (((status <> 'active'::text) OR (path_ref IS NOT NULL)))`
- `enterprise.mastery_path_operations.mastery_path_operations_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'completed'::text, 'failed'::text, 'interrupted'::text])))`
- `enterprise.mastery_topic_meta.mastery_topic_meta_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'archived'::text])))`
- `enterprise.mastery_topic_sources.mastery_topic_sources_check` — `CHECK (((kind <> 'chat'::text) OR (external_id <> ''::text)))`
- `enterprise.mastery_topic_sources.mastery_topic_sources_kind_check` — `CHECK ((kind = ANY (ARRAY['goal'::text, 'book'::text, 'notebook'::text, 'knowledge_base'::text, 'file'::text, 'chat'::text, 'question_bank'::text, 'cowriter'::text, 'partner_group'::text])))`
- `enterprise.matrix_device_trust_state.matrix_device_trust_state_state_check` — `CHECK ((state = ANY (ARRAY['unset'::text, 'verified'::text, 'blacklisted'::text, 'ignored'::text])))`
- `enterprise.messages.messages_role_check` — `CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'system'::text, 'tool'::text])))`
- `enterprise.notebook_entries.notebook_entries_check` — `CHECK (((source <> 'immersive_reading'::text) OR (material_id <> ''::text)))`
- `enterprise.notebook_entries.notebook_entries_score_trend_check` — `CHECK ((score_trend = ANY (ARRAY['new'::text, 'unchanged'::text, 'improved'::text, 'declined'::text])))`
- `enterprise.notebook_entries.notebook_entries_source_check` — `CHECK ((source = ANY (ARRAY['deep_question'::text, 'book'::text, 'mastery_path'::text, 'immersive_reading'::text])))`
- `enterprise.notebook_entries.notebook_mastery_path_required` — `CHECK (((source <> 'mastery_path'::text) OR (material_id <> ''::text)))`
- `enterprise.operations.operations_check` — `CHECK ((((status = 'deleted'::text) AND (request IS NULL) AND (session_id IS NULL) AND (turn_id IS NULL)) OR ((status = 'registered'::text) AND (request IS NOT NULL) AND (session_id IS NOT NULL) AND (turn_id IS NOT NULL))))`
- `enterprise.operations.operations_status_check` — `CHECK ((status = ANY (ARRAY['registered'::text, 'deleted'::text])))`
- `enterprise.partner_runtime_status.partner_runtime_status_state_check` — `CHECK ((state = ANY (ARRAY['running'::text, 'stopped'::text, 'reload_failed'::text, 'start_failed'::text])))`
- `enterprise.reading_materials.reading_materials_source_kind_check` — `CHECK ((source_kind = ANY (ARRAY['file'::text, 'web'::text, 'video'::text, 'youtube'::text, 'bilibili'::text, 'audio'::text])))`
- `enterprise.reading_materials.reading_materials_status_check` — `CHECK ((status = ANY (ARRAY['queued'::text, 'processing'::text, 'ready'::text, 'failed'::text])))`
- `enterprise.reading_materials.reading_materials_check` — `CHECK (((status = 'ready'::text) = (progress = 100)))`
- `enterprise.resource_cleanup_jobs.resource_cleanup_jobs_state_check` — `CHECK ((state = ANY (ARRAY['pending'::text, 'running'::text, 'failed'::text, 'done'::text])))`
- `enterprise.resource_objects.resource_objects_content_hash_check` — `CHECK (((content_hash = ''::text) OR (length(content_hash) = 64)))`
- `enterprise.resource_objects.resource_objects_retention_check` — `CHECK ((retention = ANY (ARRAY['default'::text, 'temporary'::text, 'retained'::text, 'legal-hold'::text])))`
- `enterprise.resource_objects.resource_objects_state_check` — `CHECK ((state = ANY (ARRAY['pending'::text, 'uploaded'::text, 'ready'::text, 'delete-pending'::text, 'deleted'::text, 'failed'::text])))`
- `enterprise.runtime_audit_events.runtime_audit_events_scope_kind_check` — `CHECK ((scope_kind = ANY (ARRAY['platform'::text, 'tenant'::text, 'owner'::text, 'resource'::text])))`
- `enterprise.runtime_policies.runtime_policies_status_check` — `CHECK ((status = ANY (ARRAY['draft'::text, 'saved'::text, 'active'::text, 'failed'::text, 'draining'::text])))`
- `enterprise.runtime_policies.runtime_policies_subject_kind_check` — `CHECK ((subject_kind = ANY (ARRAY['tenant'::text, 'owner'::text, 'role'::text, 'tool'::text, 'model'::text])))`
- `enterprise.runtime_settings.runtime_settings_scope_kind_check` — `CHECK ((scope_kind = ANY (ARRAY['platform'::text, 'tenant'::text, 'owner'::text])))`
- `enterprise.runtime_settings.runtime_settings_status_check` — `CHECK ((status = ANY (ARRAY['draft'::text, 'saved'::text, 'active'::text, 'failed'::text, 'draining'::text])))`
- `enterprise.secret_references.secret_references_scope_kind_check` — `CHECK ((scope_kind = ANY (ARRAY['platform'::text, 'tenant'::text, 'owner'::text])))`
- `enterprise.secret_references.secret_references_status_check` — `CHECK ((status = ANY (ARRAY['saved'::text, 'active'::text, 'failed'::text, 'draining'::text, 'missing'::text])))`
- `enterprise.session_objects.session_objects_state_check` — `CHECK ((state = ANY (ARRAY['candidate'::text, 'ready'::text, 'cleanup'::text, 'deleted'::text])))`
- `enterprise.session_references.session_references_kind_check` — `CHECK ((kind = ANY (ARRAY['mastery_path_id'::text, 'reading_workspace_id'::text, 'reading_material_id'::text])))`
- `enterprise.session_references.session_references_source_kind_check` — `CHECK ((source_kind = ANY (ARRAY['preferences'::text, 'message'::text, 'turn'::text])))`
- `enterprise.tenants.tenants_external_eligibility_check` — `CHECK ((external_eligibility = ANY (ARRAY['not_required'::text, 'allowed'::text, 'denied'::text])))`
- `enterprise.tenants.tenants_provisioning_status_check` — `CHECK ((provisioning_status = ANY (ARRAY['pending'::text, 'ready'::text, 'failed'::text])))`
- `enterprise.tenants.tenants_recovery_state_check` — `CHECK ((recovery_state = ANY (ARRAY['normal'::text, 'quarantined'::text])))`
- `enterprise.turn_commands.turn_commands_kind_check` — `CHECK ((kind = ANY (ARRAY['reply'::text, 'cancel'::text])))`
- `enterprise.turns.turns_status_check` — `CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'waiting_input'::text, 'completed'::text, 'cancelled'::text, 'failed'::text])))`
- `enterprise.users.users_preset_check` — `CHECK ((preset = ANY (ARRAY['standard'::text, 'learner'::text, 'custom'::text])))`
- `enterprise.users.users_role_check` — `CHECK ((role = ANY (ARRAY['tenant_admin'::text, 'user'::text])))`
- `management.action_catalog.action_catalog_allowed_scope_check` — `CHECK ((allowed_scope = ANY (ARRAY['platform'::text, 'school'::text, 'both'::text])))`
- `management.action_catalog.action_catalog_application_check` — `CHECK ((application = ANY (ARRAY['oms'::text, 'tms'::text])))`
- `management.action_catalog.action_catalog_check` — `CHECK ((((application = 'oms'::text) AND (action_key ~~ 'ops.%'::text)) OR ((application = 'tms'::text) AND (action_key ~~ 'tenant.%'::text))))`
- `management.action_catalog.action_catalog_check1` — `CHECK (((application = 'oms'::text) OR (allowed_scope = 'school'::text)))`
- `management.action_catalog.action_catalog_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'retired'::text])))`
- `management.approval_requests.approval_distinct_reviewer` — `CHECK (((status <> 'approved'::text) OR ((reviewer_issuer IS NOT NULL) AND (reviewer_subject IS NOT NULL) AND (decided_at IS NOT NULL) AND ((reviewer_issuer <> proposer_issuer) OR (reviewer_subject <> proposer_subject)))))`
- `management.approval_requests.approval_requests_application_check` — `CHECK ((application = ANY (ARRAY['oms'::text, 'tms'::text])))`
- `management.approval_requests.approval_requests_check` — `CHECK ((((application = 'oms'::text) AND (operation <> 'school_activation'::text)) OR ((application = 'tms'::text) AND (operation = 'school_activation'::text) AND (school_id IS NOT NULL))))`
- `management.approval_requests.approval_requests_operation_check` — `CHECK ((operation = ANY (ARRAY['platform_grant'::text, 'delegation_expand'::text, 'school_activation'::text])))`
- `management.approval_requests.approval_requests_status_check` — `CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text, 'expired'::text, 'withdrawn'::text, 'failed'::text])))`
- `management.assignments.assignments_application_check` — `CHECK ((application = ANY (ARRAY['oms'::text, 'tms'::text])))`
- `management.assignments.assignments_check1` — `CHECK ((((scope_kind = 'platform'::text) AND (school_id IS NULL) AND (application = 'oms'::text)) OR ((scope_kind = 'school'::text) AND (school_id IS NOT NULL))))`
- `management.assignments.assignments_check2` — `CHECK ((((status = 'active'::text) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (revoked_at IS NOT NULL))))`
- `management.assignments.assignments_school_binding_version_valid` — `CHECK ((((scope_kind = 'platform'::text) AND (school_binding_version IS NULL)) OR ((scope_kind = 'school'::text) AND ((school_binding_version IS NULL) OR (school_binding_version > 0)))))`
- `management.assignments.assignments_scope_kind_check` — `CHECK ((scope_kind = ANY (ARRAY['platform'::text, 'school'::text])))`
- `management.assignments.assignments_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))`
- `management.audit_events.audit_events_application_check` — `CHECK ((application = ANY (ARRAY['oms'::text, 'tms'::text])))`
- `management.audit_events.audit_events_check2` — `CHECK ((((application = 'oms'::text) AND (action_key ~~ 'ops.%'::text)) OR ((application = 'tms'::text) AND (action_key ~~ 'tenant.%'::text))))`
- `management.audit_events.audit_events_result_check` — `CHECK ((result = ANY (ARRAY['success'::text, 'denied'::text, 'conflict'::text, 'failed'::text])))`
- `management.delegation_policies.delegation_policies_application_check` — `CHECK ((application = ANY (ARRAY['oms'::text, 'tms'::text])))`
- `management.delegation_policies.delegation_policies_check1` — `CHECK ((((scope_kind = 'platform'::text) AND (school_id IS NULL) AND (application = 'oms'::text)) OR ((scope_kind = 'school'::text) AND (school_id IS NOT NULL))))`
- `management.delegation_policies.delegation_policies_scope_kind_check` — `CHECK ((scope_kind = ANY (ARRAY['platform'::text, 'school'::text])))`
- `management.delegation_policies.delegation_policies_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))`
- `management.principals.principals_application_check` — `CHECK ((application = ANY (ARRAY['oms'::text, 'tms'::text])))`
- `management.principals.principals_check` — `CHECK ((((application = 'oms'::text) AND (school_id IS NULL)) OR ((application = 'tms'::text) AND (school_id IS NOT NULL))))`
- `management.principals.principals_status_check` — `CHECK ((status = ANY (ARRAY['pending'::text, 'active'::text, 'disabled'::text])))`
- `management.role_versions.role_versions_application_check` — `CHECK ((application = ANY (ARRAY['oms'::text, 'tms'::text])))`
- `management.role_versions.role_versions_check` — `CHECK (((application = 'oms'::text) OR (scope_kind = 'school'::text)))`
- `management.role_versions.role_versions_scope_kind_check` — `CHECK ((scope_kind = ANY (ARRAY['platform'::text, 'school'::text])))`
- `oms.attempt_evidence_events.attempt_evidence_events_event_kind_check` — `CHECK ((event_kind = ANY (ARRAY['dispatch_intent'::text, 'remote_unknown'::text, 'provider_usage'::text, 'verified_reconciliation'::text, 'confirmed_not_sent'::text, 'overage'::text])))`
- `oms.audit_events.audit_events_result_check` — `CHECK ((result = ANY (ARRAY['success'::text, 'denied'::text, 'conflict'::text, 'failed'::text])))`
- `oms.grant_commands.grant_commands_result_check` — `CHECK ((result = ANY (ARRAY['pending'::text, 'success'::text, 'denied'::text])))`
- `oms.quota_grants.quota_grants_acquisition_method_check` — `CHECK ((acquisition_method = ANY (ARRAY['gift'::text, 'recharge'::text])))`
- `oms.quota_grants.quota_grants_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text, 'expired'::text])))`
- `oms.school_bindings.school_bindings_status_check` — `CHECK ((status = ANY (ARRAY['pending'::text, 'verified'::text, 'revoked'::text])))`
- `oms.school_bindings.school_bindings_check` — `CHECK (((status = 'verified'::text) = ((verified_at IS NOT NULL) AND (verified_by IS NOT NULL) AND (length(TRIM(BOTH FROM verified_by)) > 0))))`
- `oms.service_definitions.service_definitions_resource_category_check` — `CHECK ((resource_category = ANY (ARRAY['model_external'::text, 'agent_capability'::text, 'tool_integration'::text, 'knowledge_content'::text, 'runtime'::text])))`
- `oms.supply_lots.supply_lots_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))`
- `oms.supply_lots.supply_lots_verified_native` — `CHECK (((supply_basis = ANY (ARRAY['legacy_unverified'::text, 'native_units'::text, 'money'::text, 'credits'::text, 'paygo'::text])) AND ((supply_basis = ANY (ARRAY['legacy_unverified'::text, 'native_units'::text])) OR (hard_ceiling IS NULL)) AND ((verified_at IS NULL) OR ((supply_basis = 'native_units'::text) AND (hard_ceiling IS NOT NULL))) AND ((created_by IS NULL) OR (length(created_by) > 0)) AND (version >= 1)))`
- `oms.tenant_service_entitlements.tenant_service_entitlements_status_check` — `CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))`
- `oms.usage_attempts.usage_attempts_status_check` — `CHECK ((status = ANY (ARRAY['reserved'::text, 'dispatched'::text, 'remote_unknown'::text, 'reconcile_required'::text, 'settled'::text, 'released'::text])))`
- `oms.usage_attempts.usage_attempts_subject_kind_check` — `CHECK ((subject_kind = ANY (ARRAY['user'::text, 'delegated_user'::text, 'app'::text, 'service'::text])))`
## 集中清理迁移后的最终 catalog 复核（2026-09-28）

在隔离合成 PostgreSQL 空库上应用当前工作区全部 core、EduPlus2 receiver、OMS 与 Management 迁移后，`test_final_schema_has_no_database_owned_business_rules` 查询 `enterprise`、`eduplus2`、`oms`、`management` 的 catalog：

- 用户定义函数/存储过程：0
- 非内部应用触发器：0
- PostgreSQL ENUM 类型：0
- 117 项已登记枚举/条件业务 CHECK：0
- 保留 CHECK：仅 3 项非枚举物理约束（`mastery_events_check`、`mastery_interactions_check`、`resource_objects_content_hash_check`）及其它非业务物理/JSON 形状约束。

此复核只证明隔离合成库的最终 schema 形态；8.x 仍需完整注入、回归、安全与发布边界验收。

