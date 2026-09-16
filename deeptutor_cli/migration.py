"""离线迁移工具命令。

这些命令只处理显式 manifest / snapshot 制品；不装配业务运行容器、不连接
PostgreSQL、不读取模型 Secret，也不触发旧 SQLite Store 的自动迁移。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import typer


def _echo_json(payload: dict) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def register(app: typer.Typer) -> None:
    migration = typer.Typer(help="Offline PostgreSQL cutover and source checks.")
    sqlite = typer.Typer(help="SQLite source snapshot, source-check and plan.")
    pocketbase = typer.Typer(help="PocketBase read-only export and source-check.")
    data = typer.Typer(help="Offline data/ inventory, plan, verify and report.")
    migration.add_typer(sqlite, name="sqlite")
    migration.add_typer(pocketbase, name="pocketbase")
    migration.add_typer(data, name="data")
    app.add_typer(migration, name="migration")

    @data.command("inventory")
    def data_inventory(
        source_root: Path = typer.Option(..., "--source-root", help="Read-only data/ root."),
        source_id: str = typer.Option("", "--source-id", help="Stable source snapshot id."),
        target_tenant: str = typer.Option("", "--target-tenant", help="Target tenant id."),
        owner_map: list[str] = typer.Option(
            [],
            "--owner-map",
            help="Source-to-target owner mapping in source=target form. Repeatable.",
        ),
        expect_source_fingerprint: str = typer.Option(
            "",
            "--expect-source-fingerprint",
            help="Expected source fingerprint; mismatch blocks replay/import promotion.",
        ),
    ) -> None:
        from deeptutor.runtime.data_gate import default_data_use_inventory

        root = source_root.resolve()
        owner_mappings: dict[str, str] = {}
        for item in owner_map:
            if "=" not in item:
                _echo_json(
                    {
                        "ok": False,
                        "mode": "inventory",
                        "rows": [],
                        "errors": [{"reason_code": "invalid_owner_map"}],
                    }
                )
                raise typer.Exit(1)
            source_owner, target_owner = item.split("=", 1)
            owner_mappings[source_owner] = target_owner
        declarations = sorted(
            default_data_use_inventory(),
            key=lambda item: len(item.normalized_path().parts),
            reverse=True,
        )
        rows: list[dict] = []
        errors: list[dict] = []
        if not root.exists() or not root.is_dir():
            _echo_json({"ok": False, "mode": "inventory", "rows": [], "errors": [{"reason_code": "source_root_missing"}]})
            raise typer.Exit(1)

        def classify(relative: Path):
            for item in declarations:
                normalized = item.normalized_path()
                if relative == normalized or normalized in relative.parents:
                    return item
            return None

        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            rel_text = rel.as_posix()
            if path.is_symlink():
                try:
                    target = path.resolve(strict=True)
                except OSError:
                    target = None
                if target is None or root not in target.parents and target != root:
                    errors.append({"source_path": rel_text, "reason_code": "symlink_escape"})
                    continue
            if not path.is_file():
                continue
            declaration = classify(rel)
            category = declaration.category.value if declaration else "forbidden-authority"
            source_kind = declaration.name if declaration else "unknown"
            data = path.read_bytes()
            owner_source = next(iter(owner_mappings), "")
            owner_target = owner_mappings.get(owner_source, "")
            owner_hash = hashlib.sha256(owner_target.encode()).hexdigest() if owner_target else ""
            row = {
                "source_path": rel_text,
                "source_kind": source_kind,
                "category": category,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
                "owner_source": owner_source,
                "tenant_target": target_tenant,
                "owner_target": owner_target,
                "object_prefix": (
                    f"tenants/{target_tenant}/owners/{owner_hash}/{source_kind}/"
                    if target_tenant and owner_target
                    else ""
                ),
                "sensitive_fields": [],
                "target_provider": "objectstore",
                "decision": "import",
                "reason_code": "object_resource",
            }
            lower_name = path.name.lower()
            if source_kind in {"settings", "system", "system_user_secrets"} or lower_name.endswith(
                (".json", ".yaml", ".yml")
            ):
                try:
                    payload = json.loads(data.decode("utf-8"))
                except Exception:
                    payload = {}
                if isinstance(payload, dict):
                    sensitive = sorted(
                        key
                        for key in payload
                        if any(token in key.lower() for token in ("secret", "token", "password", "api_key", "dsn", "key"))
                    )
                    if sensitive:
                        row.update(
                            {
                                "sensitive_fields": sensitive,
                                "target_provider": "secret-provider",
                                "decision": "manual-secret-map",
                                "reason_code": "secret_plaintext_mapping_required",
                            }
                        )
                    else:
                        row.update({"target_provider": "settings-provider", "reason_code": "settings_provider"})
            rows.append(row)
        source_fingerprint = hashlib.sha256(
            "\n".join(
                f"{row['source_path']}:{row['sha256']}:{row['size_bytes']}" for row in rows
            ).encode()
        ).hexdigest()
        if expect_source_fingerprint and expect_source_fingerprint != source_fingerprint:
            errors.append(
                {
                    "reason_code": "source_fingerprint_mismatch",
                    "expected": expect_source_fingerprint,
                    "actual": source_fingerprint,
                }
            )
        report = {
            "ok": not errors,
            "mode": "inventory",
            "source_root": str(root),
            "source_id": source_id,
            "source_fingerprint": source_fingerprint,
            "owner_mappings": owner_mappings,
            "rows": rows,
            "errors": errors,
        }
        _echo_json(report)
        if errors:
            raise typer.Exit(1)

    @sqlite.command("snapshot")
    def snapshot(
        source: Path = typer.Option(..., "--source", help="Source SQLite database path."),
        output_dir: Path = typer.Option(..., "--output-dir", help="Artifact output directory."),
        source_id: str = typer.Option(..., "--source-id", help="Stable source identifier."),
        source_version: str = typer.Option(
            "chat_history_sqlite/v1",
            "--source-version",
            help="Registered source format version.",
        ),
        source_owner: str = typer.Option(..., "--source-owner", help="Source owner id."),
        target_owner: str = typer.Option(..., "--target-owner", help="Target PG owner id."),
        target_tenant: str = typer.Option(..., "--target-tenant", help="Target tenant id."),
        freeze_id: str = typer.Option(..., "--freeze-id", help="Approved freeze id."),
        stopped_writer: list[str] = typer.Option(
            ...,
            "--stopped-writer",
            help="Writer stopped as part of the freeze window. Repeatable.",
        ),
        operator: str = typer.Option("", "--operator", help="Operator/evidence label."),
    ) -> None:
        from deeptutor.persistence.postgres.offline_import import create_sqlite_source_snapshot

        try:
            result = create_sqlite_source_snapshot(
                source_db=source,
                output_dir=output_dir,
                source_id=source_id,
                source_version=source_version,
                source_owner_id=source_owner,
                target_tenant_id=target_tenant,
                owner_mappings={source_owner: target_owner},
                freeze_id=freeze_id,
                stopped_writers=stopped_writer,
                operator=operator,
            )
        except Exception as exc:
            typer.echo("SQLite source snapshot failed; source was not modified by this tool", err=True)
            raise typer.Exit(1) from exc
        _echo_json(
            {
                "ok": True,
                "manifest_path": str(result.manifest_path),
                "snapshot_path": str(result.snapshot_path),
                "source_id": result.source_id,
            }
        )

    @sqlite.command("source-check")
    def source_check(
        manifest: Path = typer.Option(..., "--manifest", help="Offline manifest path."),
    ) -> None:
        from deeptutor.persistence.postgres.offline_import import source_check_manifest

        report = source_check_manifest(manifest)
        _echo_json(report.to_dict())
        if not report.ok:
            raise typer.Exit(1)

    @sqlite.command("plan")
    def plan(
        manifest: Path = typer.Option(..., "--manifest", help="Offline manifest path."),
    ) -> None:
        from deeptutor.persistence.postgres.offline_import import plan_sqlite_import

        report = plan_sqlite_import(manifest)
        _echo_json(report.to_dict())
        if not report.ok:
            raise typer.Exit(1)

    @pocketbase.command("export")
    def pocketbase_export(
        endpoint: str = typer.Option(..., "--endpoint", help="PocketBase base URL."),
        output_dir: Path = typer.Option(..., "--output-dir", help="Artifact output directory."),
        source_id: str = typer.Option(..., "--source-id", help="Stable source identifier."),
        source_owner: str = typer.Option(..., "--source-owner", help="Source PocketBase user id."),
        target_owner: str = typer.Option(..., "--target-owner", help="Target PG owner id."),
        target_tenant: str = typer.Option(..., "--target-tenant", help="Target tenant id."),
        freeze_id: str = typer.Option(..., "--freeze-id", help="Approved freeze id."),
        stopped_writer: list[str] = typer.Option(
            ...,
            "--stopped-writer",
            help="Writer stopped as part of the freeze window. Repeatable.",
        ),
        operator: str = typer.Option("", "--operator", help="Operator/evidence label."),
        admin_email: str = typer.Option("", "--admin-email", help="Optional admin email."),
        admin_password_env: str = typer.Option(
            "POCKETBASE_ADMIN_PASSWORD",
            "--admin-password-env",
            help="Environment variable that contains the admin password.",
        ),
        page_size: int = typer.Option(200, "--page-size", min=1, max=500),
    ) -> None:
        from deeptutor.persistence.postgres.offline_import import create_pocketbase_source_export

        try:
            from pocketbase import PocketBase  # type: ignore[import]
        except ImportError as exc:
            typer.echo("PocketBase SDK is not installed. Install the server extra first.", err=True)
            raise typer.Exit(1) from exc

        pb = PocketBase(endpoint.rstrip("/"))
        if admin_email:
            password = os.environ.get(admin_password_env, "")
            if not password:
                typer.echo(f"Missing PocketBase admin password env: {admin_password_env}", err=True)
                raise typer.Exit(1)
            pb.admins.auth_with_password(admin_email, password)
        try:
            result = create_pocketbase_source_export(
                pb_client=pb,
                source_endpoint=endpoint,
                output_dir=output_dir,
                source_id=source_id,
                source_owner_id=source_owner,
                target_tenant_id=target_tenant,
                owner_mappings={source_owner: target_owner},
                freeze_id=freeze_id,
                stopped_writers=stopped_writer,
                operator=operator,
                page_size=page_size,
            )
        except Exception as exc:
            typer.echo("PocketBase export failed; remote service was not modified", err=True)
            raise typer.Exit(1) from exc
        _echo_json(
            {
                "ok": True,
                "manifest_path": str(result.manifest_path),
                "snapshot_path": str(result.snapshot_path),
                "source_id": result.source_id,
            }
        )
