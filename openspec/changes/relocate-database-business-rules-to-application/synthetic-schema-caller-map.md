# 枚举/状态 CHECK 表的程序引用（静态初筛）

主体按 DeepTutor 产品源 `deeptutor/` 与 `extensions/enterprise/src/` 的字面 `schema.table` 搜索生成；下方另列已人工复核的动态 SQL。表别名通过所属语句计入字面引用；外部直接 SQL 不属于受支持写入口，迁移 SQL 作为结构/模板来源另见目录清单。行号按生成时工作树。

## 动态 SQL 与零字面引用复核

- `deeptutor/persistence/postgres/learning/bindings.py` 的动态表/列仅来自封闭二元组 `mastery_interactions.result`、`mastery_events.payload`，用途是删除会话时同事务保留脱敏来源。
- `deeptutor/persistence/postgres/notebook.py` 的动态 `SET` 字段来自前置字段白名单，仅更新 `enterprise.notebook_entries`；`session.py` 动态 `field` 仅为 `turns.user_message_id` / `turns.assistant_message_id`。
- `deeptutor/persistence/postgres/offline_import/id_mapping.py` 按显式传入且经标识符转义的表/列读 identity 最大值；`offline_import/cutover.py` 从 `information_schema` 枚举 `enterprise` 含 `tenant_id` 的表做只读行数/摘要验证。`offline_import/stage.py` 动态删表仅位于 `migration_stage`，不属于本清单的业务枚举 CHECK。
- `eduplus2.provider_clients` 与 `management.approval_requests` 在当前在线 Python 中无字面或动态业务写入；只有历史迁移建表和受控维护/迁移 runner 校验。`provider_clients` 已由 Enterprise runner 逐行校验维护目录值域；`approval_requests` 已由 Management approval snapshot 校验。未来正式在线审批写入口仍须另按 5.9 接入程序校验。

## `eduplus2.audit_events`
`extensions/enterprise/src/deeptutor_enterprise/eduplus2/service.py:142,167,212,891`, `extensions/enterprise/src/deeptutor_enterprise/api/application.py:119`

## `eduplus2.audit_export_jobs`
`extensions/enterprise/src/deeptutor_enterprise/eduplus2/service.py:949`

## `eduplus2.external_client_registrations`
`extensions/enterprise/src/deeptutor_enterprise/eduplus2/service.py:658,1117,1232,1257,1350,1374`, `extensions/enterprise/src/deeptutor_enterprise/eduplus2/webhook_authority.py:104,267,279,292,299,316`, `extensions/enterprise/src/deeptutor_enterprise/eduplus2/lifecycle.py:193,348,533`, `extensions/enterprise/src/deeptutor_enterprise/management/tms_identity.py:70`

## `eduplus2.identity_bindings`
`extensions/enterprise/src/deeptutor_enterprise/eduplus2/service.py:682,1504,1552,1570`

## `eduplus2.lifecycle_actor_candidates`
`extensions/enterprise/src/deeptutor_enterprise/eduplus2/webhook_authority.py:52,330`, `extensions/enterprise/src/deeptutor_enterprise/eduplus2/lifecycle.py:497,616`, `extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py:256,263,271`, `extensions/enterprise/src/deeptutor_enterprise/management/actor_activation.py:86,177,185`, `extensions/enterprise/src/deeptutor_enterprise/management/actor_handoff.py:46`

## `eduplus2.lifecycle_inbox`
`extensions/enterprise/src/deeptutor_enterprise/eduplus2/webhook_authority.py:28,114,138,191,351`, `extensions/enterprise/src/deeptutor_enterprise/eduplus2/lifecycle.py:160,244,251,345,476,502,609`

## `eduplus2.lifecycle_targets`
`extensions/enterprise/src/deeptutor_enterprise/eduplus2/lifecycle.py:208,212,329,422,444,548,556,597`, `extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py:238,245`

## `eduplus2.profile_snapshots`
`extensions/enterprise/src/deeptutor_enterprise/eduplus2/service.py:425`

## `eduplus2.provider_clients`
未发现字面程序引用（需人工审查）

## `eduplus2.revocation_events`
`extensions/enterprise/src/deeptutor_enterprise/eduplus2/service.py:746,754`

## `eduplus2.revocation_state`
`extensions/enterprise/src/deeptutor_enterprise/eduplus2/service.py:516,777`

## `eduplus2.webhook_school_state`
`extensions/enterprise/src/deeptutor_enterprise/bootstrap.py:224`, `extensions/enterprise/src/deeptutor_enterprise/eduplus2/webhook_authority.py:42,207,214,216,222,224,225`, `extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py:189,218`, `extensions/enterprise/src/deeptutor_enterprise/management/lifecycle_controls.py:64`, `extensions/enterprise/src/deeptutor_enterprise/management/authorization.py:210`, `extensions/enterprise/src/deeptutor_enterprise/management/actor_activation.py:60`, `extensions/enterprise/src/deeptutor_enterprise/management/actor_handoff.py:51`, `extensions/enterprise/src/deeptutor_enterprise/management/tms_identity.py:71`

## `enterprise.courses`
`deeptutor/persistence/postgres/courses.py:115,126,132`

## `enterprise.cron_executions`
`deeptutor/persistence/postgres/cron.py:431,482,543,609,621`, `deeptutor/persistence/postgres/offline_import/verify_report.py:1000`, `deeptutor/persistence/postgres/offline_import/runtime_sqlite.py:589`, `deeptutor/persistence/postgres/offline_import/cutover.py:482`

## `enterprise.cron_jobs`
`deeptutor/persistence/postgres/cron.py:216,231,260,293,302,317,333,351,390,413,498,555,564,594`, `deeptutor/persistence/postgres/offline_import/verify_report.py:944`, `deeptutor/persistence/postgres/offline_import/runtime_sqlite.py:505,523`

## `enterprise.executor_state`
`deeptutor/persistence/postgres/executor.py:39,47,64,81,98`, `deeptutor/persistence/postgres/learning/authority.py:114`, `deeptutor/persistence/postgres/learning/bindings.py:372`, `extensions/enterprise/src/deeptutor_enterprise/recovery.py:73`

## `enterprise.marginnote_objects`
`deeptutor/persistence/postgres/marginnote.py:299,308,372,420,429,456,488,512,541,565,593,602`, `deeptutor/persistence/postgres/offline_import/verify_report.py:1955`, `deeptutor/persistence/postgres/offline_import/runtime_sqlite.py:983,996,1061,1101`

## `enterprise.mastery_events`
`deeptutor/learning/runtime.py:155`, `deeptutor/persistence/postgres/learning/store.py:104`, `deeptutor/persistence/postgres/learning/bindings.py:200`, `deeptutor/persistence/postgres/learning/queries.py:89`, `deeptutor/persistence/postgres/offline_import/verify_report.py:691`, `deeptutor/persistence/postgres/offline_import/learning_reading_sqlite.py:466,925`

## `enterprise.mastery_interactions`
`deeptutor/persistence/postgres/learning/transaction.py:75,106,138`, `deeptutor/persistence/postgres/learning/bindings.py:199`, `deeptutor/persistence/postgres/learning/queries.py:119,129,138,191,273`, `deeptutor/persistence/postgres/offline_import/verify_report.py:667`, `deeptutor/persistence/postgres/offline_import/learning_reading_sqlite.py:879,899`

## `enterprise.mastery_path_leases`
`deeptutor/learning/runtime.py:225`, `deeptutor/persistence/postgres/learning/bindings.py:25,143,246,272,291,313,348,378,397`

## `enterprise.mastery_path_operations`
`deeptutor/persistence/postgres/learning/store.py:157`, `deeptutor/persistence/postgres/learning/bindings.py:63,307,324,352,393`

## `enterprise.mastery_topic_meta`
`deeptutor/persistence/postgres/learning/transaction.py:159`, `deeptutor/persistence/postgres/learning/queries.py:253,320`, `deeptutor/persistence/postgres/offline_import/verify_report.py:703`, `deeptutor/persistence/postgres/offline_import/learning_reading_sqlite.py:951,968`

## `enterprise.mastery_topic_sources`
`deeptutor/persistence/postgres/learning/transaction.py:180,195`, `deeptutor/persistence/postgres/learning/queries.py:263`, `deeptutor/persistence/postgres/offline_import/verify_report.py:715`, `deeptutor/persistence/postgres/offline_import/learning_reading_sqlite.py:992`

## `enterprise.matrix_device_trust_state`
`deeptutor/persistence/postgres/matrix.py:511,637,649,669`, `deeptutor/persistence/postgres/offline_import/verify_report.py:2063`, `deeptutor/persistence/postgres/offline_import/matrix_sqlite.py:536`

## `enterprise.messages`
`deeptutor/services/memory/snapshot/adapters.py:121,636`, `deeptutor/persistence/postgres/session_statements.py:20,30,105,109`, `deeptutor/persistence/postgres/session.py:139,163,164,738,749,937,1012,1253,1260,1308,1347,1381,1422,1484`, `deeptutor/persistence/postgres/offline_import/verify_report.py:1673`, `deeptutor/persistence/postgres/offline_import/chat_sqlite.py:213,355,539`, `deeptutor/persistence/postgres/offline_import/pocketbase_import.py:349,565,649`

## `enterprise.notebook_entries`
`deeptutor/services/memory/snapshot/adapters.py:149`, `deeptutor/persistence/postgres/session_statements.py:69`, `deeptutor/persistence/postgres/session.py:1288`, `deeptutor/persistence/postgres/notebook_upsert.py:18,99`, `deeptutor/persistence/postgres/notebook_categories.py:57,161,210`, `deeptutor/persistence/postgres/notebook.py:214,235,254,292,319,345,372,401,481,516`, `deeptutor/persistence/postgres/migrations/runner.py:309,310,311,312,313,314`, `deeptutor/persistence/postgres/learning/transaction.py:188`, `deeptutor/persistence/postgres/offline_import/verify_report.py:1523,1721`, `deeptutor/persistence/postgres/offline_import/chat_sqlite.py:258,483,540`, `deeptutor/persistence/postgres/offline_import/learning_reading_sqlite.py:246`

## `enterprise.operations`
`deeptutor/persistence/postgres/session_statements.py:81`, `deeptutor/persistence/postgres/session.py:400,405,453,1206`

## `enterprise.partner_runtime_status`
`deeptutor/persistence/postgres/partner_runtime_status.py:192,217,242,284,299,315`, `deeptutor/persistence/postgres/offline_import/verify_report.py:1038`, `deeptutor/persistence/postgres/offline_import/runtime_sqlite.py:784,817`

## `enterprise.reading_materials`
`deeptutor/persistence/postgres/session_statements.py:121`, `deeptutor/persistence/postgres/notebook_upsert.py:126`, `deeptutor/persistence/postgres/reading/materials.py:77,83,133,142,157,175,194,254`, `deeptutor/persistence/postgres/reading/pages.py:105,152`, `deeptutor/persistence/postgres/reading/queries.py:60,77,140`, `deeptutor/persistence/postgres/reading/workspaces.py:45,67,291`, `deeptutor/persistence/postgres/offline_import/verify_report.py:803`, `deeptutor/persistence/postgres/offline_import/learning_reading_sqlite.py:561,744`

## `enterprise.resource_cleanup_jobs`
`deeptutor/persistence/postgres/session_resources.py:578,641,655,671`, `deeptutor/persistence/postgres/object_resources.py:460,531,568,610,624,640,644`, `deeptutor/persistence/postgres/governance.py:287`

## `enterprise.resource_objects`
`deeptutor/services/skill/externalized.py:92`, `deeptutor/services/persona/externalized.py:54`, `deeptutor/persistence/postgres/session_resources.py:460,498,518,574,627,637,651,667`, `deeptutor/persistence/postgres/object_resources.py:186,251,278,287,326,382,413,422,454,480,496,522,567,601,618,634`, `deeptutor/persistence/postgres/governance.py:279`, `extensions/enterprise/src/deeptutor_enterprise/knowledge_bases.py:62`

## `enterprise.runtime_audit_events`
`deeptutor/persistence/postgres/governance.py:89,267`

## `enterprise.runtime_policies`
`deeptutor/multi_user/grants.py:74,92,97`

## `enterprise.runtime_settings`
`deeptutor/persistence/postgres/governance.py:148,152,184`, `extensions/enterprise/src/deeptutor_enterprise/model_catalog.py:145,174,179`

## `enterprise.secret_references`
`deeptutor/persistence/postgres/governance.py:223,229`, `extensions/enterprise/src/deeptutor_enterprise/model_catalog.py:56`

## `enterprise.session_objects`
`deeptutor/services/session/deletion.py:47`, `deeptutor/persistence/postgres/session_statements.py:77`, `deeptutor/persistence/postgres/session_resources.py:48,62,165,185,202,218,231,254,265,282,296,306,321,330,339,346,361,445,492,516,550,561,570,600,610,626,647,663,678,693`, `deeptutor/persistence/postgres/session.py:1352`

## `enterprise.session_references`
`deeptutor/persistence/postgres/session_statements.py:125,129`, `deeptutor/persistence/postgres/session_references.py:36,41`

## `enterprise.tenants`
`deeptutor/app/postgres_runtime.py:372`, `deeptutor/persistence/postgres/identity/service.py:114,120,150,180,294`, `deeptutor/persistence/postgres/identity/accounts.py:284`, `extensions/enterprise/src/deeptutor_enterprise/bootstrap.py:207,474`, `extensions/enterprise/src/deeptutor_enterprise/recovery.py:45,56,80,121`, `extensions/enterprise/src/deeptutor_enterprise/eduplus2/service.py:1587`, `extensions/enterprise/src/deeptutor_enterprise/eduplus2/webhook_authority.py:152,160,170,253,334`, `extensions/enterprise/src/deeptutor_enterprise/eduplus2/lifecycle.py:225,236,337,465,506,532,559`, `extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py:229`, `extensions/enterprise/src/deeptutor_enterprise/management/authorization.py:177`, `extensions/enterprise/src/deeptutor_enterprise/management/actor_activation.py:48,172`, `extensions/enterprise/src/deeptutor_enterprise/management/actor_handoff.py:49`, `extensions/enterprise/src/deeptutor_enterprise/management/tms_identity.py:57`

## `enterprise.turn_commands`
`deeptutor/persistence/postgres/session.py:554,570,597`

## `enterprise.turns`
`deeptutor/persistence/postgres/session_statements.py:30,65`, `deeptutor/persistence/postgres/session.py:130,166,167,335,345,471,606,676,820,881,900,945,1267,1299`, `deeptutor/persistence/postgres/migrations/runner.py:773`, `deeptutor/persistence/postgres/learning/authority.py:80,126`, `deeptutor/persistence/postgres/learning/bindings.py:53,193,385`, `deeptutor/persistence/postgres/offline_import/verify_report.py:1480,1687,1875`, `deeptutor/persistence/postgres/offline_import/chat_sqlite.py:397,555`, `deeptutor/persistence/postgres/offline_import/learning_reading_sqlite.py:236`, `deeptutor/persistence/postgres/offline_import/pocketbase_import.py:594`

## `enterprise.users`
`deeptutor/multi_user/grants.py:53`, `deeptutor/services/cron/postgres.py:88`, `deeptutor/persistence/postgres/session_resources.py:117,394`, `deeptutor/persistence/postgres/object_resources.py:86`, `deeptutor/persistence/postgres/identity/service.py:126,136,142,179,293,362,370,394,420,424`, `deeptutor/persistence/postgres/identity/accounts.py:94,106,128,145,169,184,203,224,257,284,359`, `deeptutor/persistence/postgres/offline_import/verify_report.py:1910`, `deeptutor/persistence/postgres/offline_import/runtime_sqlite.py:146`, `deeptutor/persistence/postgres/offline_import/cutover.py:402`, `deeptutor/persistence/postgres/offline_import/chat_sqlite.py:177`, `deeptutor/persistence/postgres/offline_import/learning_reading_sqlite.py:123`, `deeptutor/persistence/postgres/offline_import/matrix_sqlite.py:111`, `deeptutor/persistence/postgres/offline_import/pocketbase_import.py:251,512`, `extensions/enterprise/src/deeptutor_enterprise/bootstrap.py:613`, `extensions/enterprise/src/deeptutor_enterprise/recovery.py:60,93,104,114`, `extensions/enterprise/src/deeptutor_enterprise/eduplus2/service.py:1538,1545,1587`

## `management.action_catalog`
`extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py:741`, `extensions/enterprise/src/deeptutor_enterprise/management/grants.py:151`, `extensions/enterprise/src/deeptutor_enterprise/management/authorization.py:254,333`

## `management.approval_requests`
未发现字面程序引用（需人工审查）

## `management.assignments`
`extensions/enterprise/src/deeptutor_enterprise/management/grants.py:195,225,247,339,357,405`, `extensions/enterprise/src/deeptutor_enterprise/management/authorization.py:251`, `extensions/enterprise/src/deeptutor_enterprise/management/actor_activation.py:113,141,164`

## `management.audit_events`
`extensions/enterprise/src/deeptutor_enterprise/oms/skill_store.py:119`, `extensions/enterprise/src/deeptutor_enterprise/oms/model_drafts.py:73`, `extensions/enterprise/src/deeptutor_enterprise/management/lifecycle_controls.py:76,212`, `extensions/enterprise/src/deeptutor_enterprise/management/grants.py:196,272,370,419`, `extensions/enterprise/src/deeptutor_enterprise/management/actor_activation.py:192`

## `management.delegation_policies`
`extensions/enterprise/src/deeptutor_enterprise/management/authorization.py:332`

## `management.principals`
`extensions/enterprise/src/deeptutor_enterprise/oms/identity.py:169`, `extensions/enterprise/src/deeptutor_enterprise/management/grants.py:173,241,267,348,415`, `extensions/enterprise/src/deeptutor_enterprise/management/authorization.py:152`, `extensions/enterprise/src/deeptutor_enterprise/management/actor_activation.py:104,152,158`, `extensions/enterprise/src/deeptutor_enterprise/management/tms_identity.py:101`

## `management.role_versions`
`extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py:757`, `extensions/enterprise/src/deeptutor_enterprise/management/grants.py:136`

## `oms.attempt_evidence_events`
`extensions/enterprise/src/deeptutor_enterprise/oms/attempts.py:158`

## `oms.audit_events`
`extensions/enterprise/src/deeptutor_enterprise/oms/ledger.py:464,688,889`, `extensions/enterprise/src/deeptutor_enterprise/oms/entitlements.py:213`, `extensions/enterprise/src/deeptutor_enterprise/oms/supply.py:182,244`, `extensions/enterprise/src/deeptutor_enterprise/oms/attempts.py:169`

## `oms.grant_commands`
`extensions/enterprise/src/deeptutor_enterprise/oms/ledger.py:229,246,486,540,558,704,725,742,915`

## `oms.quota_grants`
`extensions/enterprise/src/deeptutor_enterprise/oms/ledger.py:272,311,445,577,624,680,850`, `extensions/enterprise/src/deeptutor_enterprise/oms/entitlements.py:183`, `extensions/enterprise/src/deeptutor_enterprise/oms/attempts.py:321,471,575`, `extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py:436,518`

## `oms.school_bindings`
`extensions/enterprise/src/deeptutor_enterprise/bootstrap.py:223`, `extensions/enterprise/src/deeptutor_enterprise/eduplus2/webhook_authority.py:152,177`, `extensions/enterprise/src/deeptutor_enterprise/eduplus2/lifecycle.py:227,235,336,429,532,557`, `extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py:450,474`, `extensions/enterprise/src/deeptutor_enterprise/management/authorization.py:176`, `extensions/enterprise/src/deeptutor_enterprise/management/actor_activation.py:48`, `extensions/enterprise/src/deeptutor_enterprise/management/actor_handoff.py:47`, `extensions/enterprise/src/deeptutor_enterprise/management/tms_identity.py:56`

## `oms.service_definitions`
`extensions/enterprise/src/deeptutor_enterprise/oms/ledger.py:776`, `extensions/enterprise/src/deeptutor_enterprise/oms/entitlements.py:141,173`, `extensions/enterprise/src/deeptutor_enterprise/oms/supply.py:206`, `extensions/enterprise/src/deeptutor_enterprise/oms/attempts.py:277`

## `oms.supply_lots`
`extensions/enterprise/src/deeptutor_enterprise/oms/ledger.py:292,335,364,386,423,597,643,669,763,813,870`, `extensions/enterprise/src/deeptutor_enterprise/oms/supply.py:135,158,174,215,290`, `extensions/enterprise/src/deeptutor_enterprise/oms/attempts.py:323,397,472,576,678`, `extensions/enterprise/src/deeptutor_enterprise/migrations/runner.py:498`

## `oms.tenant_service_entitlements`
`extensions/enterprise/src/deeptutor_enterprise/oms/ledger.py:281,586,787`, `extensions/enterprise/src/deeptutor_enterprise/oms/entitlements.py:131,148,193`, `extensions/enterprise/src/deeptutor_enterprise/oms/attempts.py:290`

## `oms.usage_attempts`
`extensions/enterprise/src/deeptutor_enterprise/oms/attempts.py:212,226,265,308,359,431,448,494,552,603`
