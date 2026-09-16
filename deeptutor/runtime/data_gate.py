"""Production/Kubernetes data-directory gate.

The gate is intentionally value-free: it reports stable codes and relative
paths only, never provider URLs, DSNs, object keys, or Secret values.  It is the
first fail-closed layer for the OpenSpec change that makes ``data/`` non-
authoritative in Kubernetes runtime.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path


class DataUseCategory(str, Enum):
    FORBIDDEN_AUTHORITY = "forbidden-authority"
    EXTERNALIZED = "externalized"
    PROJECTION = "projection"
    SCRATCH = "scratch"
    CACHE = "cache"
    OFFLINE_IMPORT_INPUT = "offline-import-input"
    LOCAL_DEV_ONLY = "local-dev-only"


@dataclass(frozen=True, slots=True)
class RuntimeMode:
    """Explicit DeepTutor runtime mode.

    Local development remains the default so importing CLI/SDK/help does not
    unexpectedly require production infrastructure.  Kubernetes manifests must
    opt in with ``DEEPTUTOR_RUNTIME_MODE=production`` or ``kubernetes``.
    """

    name: str = "local"

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "RuntimeMode":
        source = os.environ if environ is None else environ
        raw = str(source.get("DEEPTUTOR_RUNTIME_MODE") or "").strip().lower()
        aliases = {
            "": "local",
            "dev": "local",
            "local": "local",
            "development": "local",
            "test": "local",
            "prod": "production",
            "production": "production",
            "k8s": "kubernetes",
            "kubernetes": "kubernetes",
        }
        return cls(aliases.get(raw, raw or "local"))

    @property
    def production(self) -> bool:
        return self.name in {"production", "kubernetes"}


@dataclass(frozen=True, slots=True)
class DataUseDeclaration:
    name: str
    relative_path: str
    category: DataUseCategory
    owner_boundary: str
    entrypoints: tuple[str, ...] = ()
    reason: str = ""

    def normalized_path(self) -> Path:
        path = Path(self.relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("data-use relative_path must stay below data root")
        return path


@dataclass(frozen=True, slots=True)
class DataGateFinding:
    code: str
    name: str
    relative_path: str
    category: str
    detail: str


@dataclass(frozen=True, slots=True)
class DataGateReport:
    mode: RuntimeMode
    ready: bool
    blockers: tuple[DataGateFinding, ...]
    warnings: tuple[DataGateFinding, ...] = ()

    def safe_summary(self) -> str:
        if self.ready:
            return f"data_gate:{self.mode.name}:ready"
        codes = ",".join(sorted({finding.code for finding in self.blockers}))
        paths = ",".join(sorted({finding.relative_path for finding in self.blockers}))
        return f"data_gate:{self.mode.name}:blocked:{codes}:{paths}"

    def raise_if_blocking(self) -> None:
        if self.blockers:
            raise DataGateError(self.safe_summary(), self)


class DataGateError(RuntimeError):
    def __init__(self, message: str, report: DataGateReport):
        super().__init__(message)
        self.report = report


def default_data_use_inventory() -> tuple[DataUseDeclaration, ...]:
    """Frozen A1 inventory for production ``data/`` gate.

    This inventory records the current path-level authority boundary.  Later
    slices can move individual declarations from ``forbidden-authority`` to
    ``externalized`` once the real PG/ObjectStore/Settings provider path is
    wired and verified.
    """

    return (
        DataUseDeclaration(
            "settings",
            "user/settings",
            DataUseCategory.FORBIDDEN_AUTHORITY,
            "tenant/admin settings provider",
            ("RuntimeSettingsService", "settings/model/grants APIs"),
            "可变 settings 在 production 必须写受控 Settings/Policy provider。",
        ),
        DataUseDeclaration(
            "system",
            "system",
            DataUseCategory.FORBIDDEN_AUTHORITY,
            "platform settings/secret provider",
            ("system settings",),
            "生产 system 配置不能把 data/system 当权威。",
        ),
        DataUseDeclaration(
            "system_user_secrets",
            "system/user-secrets",
            DataUseCategory.FORBIDDEN_AUTHORITY,
            "secret provider",
            ("SecretResolver",),
            "Secret 明文只允许来自 Secret provider。",
        ),
        DataUseDeclaration(
            "owner_resources",
            "postgres-resources",
            DataUseCategory.FORBIDDEN_AUTHORITY,
            "tenant/owner resource metadata",
            ("DefaultPostgresRuntime", "OwnerResourceProvider"),
            "生产 owner 文件资源必须外置到 ObjectStore + PG metadata。",
        ),
        DataUseDeclaration(
            "workspace",
            "user/workspace",
            DataUseCategory.FORBIDDEN_AUTHORITY,
            "tenant/owner resource metadata",
            ("PathService", "workspace tools", "CLI/SDK"),
            "持久 workspace outputs 不能以 Pod 本地目录为权威。",
        ),
        DataUseDeclaration(
            "skills",
            "user/workspace/skills",
            DataUseCategory.FORBIDDEN_AUTHORITY,
            "tenant/owner skill package provider",
            ("SkillService", "read_skill", "skills API"),
            "动态 skill 正文和资源包必须来自 ObjectStore + PG metadata；Pod 本地 skills 目录不是生产权威。",
        ),
        DataUseDeclaration(
            "personas",
            "user/workspace/personas",
            DataUseCategory.FORBIDDEN_AUTHORITY,
            "tenant/owner persona provider",
            ("PersonaService", "personas API", "turn persona context"),
            "动态 persona 正文必须来自 ObjectStore + PG metadata；Pod 本地 personas 目录不是生产权威。",
        ),
        DataUseDeclaration(
            "notebooks",
            "user/workspace/notebook",
            DataUseCategory.FORBIDDEN_AUTHORITY,
            "tenant/owner notebook provider",
            ("NotebookManager", "list_notebook", "write_note"),
            "生产 notebook 正文/索引必须来自 PG 或 PG metadata + ObjectStore。",
        ),
        DataUseDeclaration(
            "knowledge_bases",
            "knowledge_bases",
            DataUseCategory.FORBIDDEN_AUTHORITY,
            "tenant/KB binding",
            ("KB import", "RAG binding"),
            "KB 原文与业务对象 metadata 必须外置。",
        ),
        DataUseDeclaration(
            "memory",
            "memory",
            DataUseCategory.FORBIDDEN_AUTHORITY,
            "tenant/owner memory provider",
            ("memory tools",),
            "生产 memory 不得回退本地 Markdown。",
        ),
        DataUseDeclaration(
            "partners",
            "partners",
            DataUseCategory.FORBIDDEN_AUTHORITY,
            "tenant/partner runtime provider",
            ("partner runtime",),
            "IM partner 运行状态需要外部 provider。",
        ),
        DataUseDeclaration(
            "runtime_state",
            "user/.runtime",
            DataUseCategory.SCRATCH,
            "process",
            ("TurnRuntimeManager",),
            "活动 turn 的临时状态可丢弃。",
        ),
        DataUseDeclaration(
            "logs",
            "user/logs",
            DataUseCategory.CACHE,
            "process/log pipeline",
            ("PathService",),
            "本地日志不是业务权威；生产日志应进入日志平台。",
        ),
        DataUseDeclaration(
            "parse_cache",
            "parse_cache",
            DataUseCategory.CACHE,
            "content-addressed cache",
            ("document parsing",),
            "解析缓存可重建。",
        ),
        DataUseDeclaration(
            "offline_import_input",
            "offline-import-input",
            DataUseCategory.OFFLINE_IMPORT_INPUT,
            "maintenance command",
            ("offline import",),
            "仅维护命令只读，不进入业务 runtime。",
        ),
    )


_LOCAL_AUTHORITY_VALUES = frozenset({"", "local", "file", "filesystem", "path", "data"})


class RuntimeDataGate:
    def __init__(
        self,
        data_root: str | Path,
        *,
        declarations: Iterable[DataUseDeclaration] | None = None,
        mode: RuntimeMode | None = None,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.mode = mode or RuntimeMode.from_environ()
        items = tuple(declarations if declarations is not None else default_data_use_inventory())
        by_name: dict[str, DataUseDeclaration] = {}
        by_path: list[tuple[Path, DataUseDeclaration]] = []
        for item in items:
            normalized = item.normalized_path()
            by_name[item.name] = item
            by_path.append((normalized, item))
        # Longest path first so nested declarations (notebooks) win over workspace.
        by_path.sort(key=lambda value: len(value[0].parts), reverse=True)
        self._by_name = by_name
        self._by_path = tuple(by_path)

    def evaluate(
        self,
        *,
        active_authorities: Mapping[str, str] | None = None,
        observed_paths: Iterable[str | Path] = (),
    ) -> DataGateReport:
        blockers: list[DataGateFinding] = []
        if self.mode.production:
            blockers.extend(self._authority_findings(active_authorities or {}))
            blockers.extend(self._path_findings(observed_paths))
        return DataGateReport(
            mode=self.mode,
            ready=not blockers,
            blockers=tuple(blockers),
        )

    def _authority_findings(self, active_authorities: Mapping[str, str]) -> list[DataGateFinding]:
        findings: list[DataGateFinding] = []
        for name, provider in active_authorities.items():
            declaration = self._by_name.get(name)
            if declaration is None:
                findings.append(
                    DataGateFinding(
                        "data_unknown_authority",
                        str(name),
                        "",
                        "unknown",
                        "active data authority has no production category",
                    )
                )
                continue
            provider_kind = str(provider or "").strip().lower()
            if (
                declaration.category
                in {DataUseCategory.FORBIDDEN_AUTHORITY, DataUseCategory.LOCAL_DEV_ONLY}
                and provider_kind in _LOCAL_AUTHORITY_VALUES
            ):
                findings.append(self._finding("data_forbidden_authority", declaration))
        return findings

    def _path_findings(self, observed_paths: Iterable[str | Path]) -> list[DataGateFinding]:
        findings: list[DataGateFinding] = []
        for raw_path in observed_paths:
            path = Path(raw_path)
            candidate = (self.data_root / path).resolve() if not path.is_absolute() else path.resolve()
            try:
                relative = candidate.relative_to(self.data_root)
            except ValueError:
                continue
            declaration = self._declaration_for(relative)
            if declaration is None:
                findings.append(
                    DataGateFinding(
                        "data_unknown_path",
                        "unknown",
                        relative.as_posix(),
                        "unknown",
                        "data path is not declared in production inventory",
                    )
                )
            elif declaration.category in {
                DataUseCategory.FORBIDDEN_AUTHORITY,
                DataUseCategory.LOCAL_DEV_ONLY,
            }:
                findings.append(self._finding("data_forbidden_authority", declaration))
        return findings

    def _declaration_for(self, relative: Path) -> DataUseDeclaration | None:
        for declared_path, declaration in self._by_path:
            try:
                relative.relative_to(declared_path)
            except ValueError:
                continue
            return declaration
        return None

    @staticmethod
    def _finding(code: str, declaration: DataUseDeclaration) -> DataGateFinding:
        return DataGateFinding(
            code,
            declaration.name,
            declaration.normalized_path().as_posix(),
            declaration.category.value,
            declaration.reason or "data path is not allowed as production authority",
        )


__all__ = [
    "DataGateError",
    "DataGateFinding",
    "DataGateReport",
    "DataUseCategory",
    "DataUseDeclaration",
    "RuntimeDataGate",
    "RuntimeMode",
    "default_data_use_inventory",
]
