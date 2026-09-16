# 旧格式代表行为基线

此目录只保存 PostgreSQL 切换前的 SQLite/JSON **离线导入与行为基线**。
这些测试必须使用 `tmp_path` 合成数据，并在进程导入 DeepTutor 前把
`DEEPTUTOR_HOME` 指向新的临时目录。它们不是业务 PostgreSQL adapter 的替身，
也不得作为运行时 provider 被引用。

推荐独立运行方式：

```bash
runtime_home="$(mktemp -d /tmp/deeptutor-task12-home.XXXXXX)"
DEEPTUTOR_HOME="$runtime_home" DT_RUN_REAL_MODEL='' \
  python -m pytest tests/persistence/legacy_baseline \
  --confcutdir=tests/persistence -q
rm -rf "$runtime_home"
```

完整 75 个既有契约节点、各领域 DTO/ID/排序/分页/冲突/CAS/删除/恢复/
owner 约束及未来真实 PG 验收项见
`tests/persistence/contracts/business-domains-v1.json`。
