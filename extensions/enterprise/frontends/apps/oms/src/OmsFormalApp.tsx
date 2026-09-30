"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Activity, Blocks, CloudCog, LayoutDashboard, Layers3, LibraryBig, Link2, Network, PackageCheck, ScrollText, ShieldCheck, Sparkles, UsersRound } from "lucide-react";
import type { ServiceView } from "@deeptutor/api-contracts";
import { AdminShell, Button, DataTable, DetailGrid, Drawer, FormModal, MetricStrip, Notice, PageHead, Section, StatePanel, StatusBadge, Tabs } from "@deeptutor/admin-ui";
import { OcrServiceList, ServiceList } from "@deeptutor/service-components";

type LoadState = "loading" | "redirecting" | "ready" | "blocked";
type ApiError = { status: number; detail: string; path?: string };
type OmsMe = { principal_id?: string; subject?: string; display_name?: string; status?: string };
type OmsPermissions = { actions?: string[]; platform_actions?: string[]; school_actions?: { school_id?: string; actions?: string[] }[]; scopes?: { kind?: string; school_id?: string; school_name?: string }[] };
type OmsSkill = {
  id?: string;
  name?: string;
  status?: string;
  revision_id?: string;
  published_revision_id?: string;
  latest_revision?: number;
  published_revision?: number;
  latest_version?: number;
  published_version?: number;
  sha256?: string;
  description?: string;
};
type OmsModelItem = { id?: string; profile_id?: string; model_id?: string; model?: string; provider?: string; status?: StatusLike; source?: string };
type ProviderConnection = { id: string; provider?: string; base_url?: string; api_key?: string };
type StatusLike = string | { code?: string; label?: string; tone?: string; description?: string };
type OmsStatusDescriptor = { code?: string; label?: string; tone?: string; description?: string };
type OmsStatusCatalog = { descriptor_version?: number; statuses?: OmsStatusDescriptor[] };
type OmsResource = { id: string; category?: string; kind?: string; status?: StatusLike; managed?: boolean; display_name?: string; safe_fields?: Record<string, unknown> };
type OmsSummary = { authorized_school_count?: number; resource_count?: number; notices?: { code?: string; label?: string; description?: string }[] };
type OmsSchoolStatusCount = { status?: StatusLike; count?: number };
type OmsSchoolQuotaGrantSummary = { status?: StatusLike; units?: string };
type OmsSchoolUsageSummary = { status?: StatusLike; attempts?: number; settled_units?: string };
type OmsSchoolProjection = {
  school_id?: string;
  school_code?: string;
  school_name?: string;
  external_binding?: { status?: StatusLike };
  lifecycle?: { external_eligibility?: StatusLike; provisioning_status?: StatusLike; recovery_state?: StatusLike };
  service_entitlements?: OmsSchoolStatusCount[];
  quota_grants?: OmsSchoolQuotaGrantSummary[];
  usage?: OmsSchoolUsageSummary[];
};
type OmsSupplyDefinition = { service_id?: string; unit_code?: string; resource_category?: string; enabled?: boolean; version?: number };
type OmsSupplyLot = { id?: string; lot_id?: string; service_id?: string; provider_id?: string; pool_id?: string; unit_code?: string; status?: StatusLike; hard_ceiling?: string | null; committed_unspent?: string; reserved_inflight?: string; version?: number };
type OmsServiceEntitlement = { id?: string; service_id?: string; status?: StatusLike; starts_at?: string; expires_at?: string; version?: number };
type OmsQuotaGrant = {
  id?: string;
  grant_id?: string;
  service_id?: string;
  unit_code?: string;
  acquisition_method?: string;
  quantity?: string;
  adjustment_released?: string;
  status?: StatusLike;
  version?: number;
  starts_at?: string;
  expires_at?: string;
  source_ref_hash?: string;
};
type OmsQuotaSummary = { school_id?: string; entitlements?: OmsServiceEntitlement[]; grants?: OmsQuotaGrant[] };
type OmsAuditEvent = { id?: string; action?: string; result?: StatusLike; request_id?: string; reason?: string };
type OmsCostProjection = { costs?: unknown[]; status?: StatusLike; notice?: string };
type OmsUsageAttempt = { attempt_id?: string; operation_id?: string; service_id?: string; unit_code?: string; status?: StatusLike; reserved_units?: string; settled_units?: string };
type OmsJob = { attempt_id?: string; operation_id?: string; service_id?: string; unit_code?: string; status?: StatusLike; reserved_units?: string; settled_units?: string };
type OmsPermissionRole = { id?: string; role_key?: string; version?: number; scope_kind?: string; actions?: string[] };
type OmsPrincipal = { id?: string; principal_id?: string; subject?: string; status?: string; policy_version?: number };
type OmsAssignment = { id?: string; assignment_id?: string; principal_id?: string; role_key?: string; role_version?: number; scope_kind?: string; school_id?: string; status?: string; version?: number };
type OmsApproval = { id?: string; approval_id?: string; operation?: string; target_principal_id?: string; status?: string; expected_target_policy_version?: number; target_role_key?: string; target_role_version?: number; target_action_keys?: string[] };
type OmsPermissionCatalog = { roles?: OmsPermissionRole[]; principals?: OmsPrincipal[]; assignments?: OmsAssignment[] };
type OmsServiceRow = ServiceView & { source?: string; rawStatus?: StatusLike };
type OmsProfileRow = { id: string; profile_id: string; provider?: string; status?: StatusLike; source?: string; service_id: string; model_count: number };
type OmsFormKey = "" | "model-draft-json" | "provider-settings-json";

const REQUEST_TIMEOUT_MS = 10_000;
const OMS_BASE = "/oms";
const OMS_NAV = [
  { label: "工作台", items: [{ label: "运营概览", href: OMS_BASE, icon: <LayoutDashboard/> }] },
  { label: "学校与权益", items: [{ label: "学校列表", href: `${OMS_BASE}/tenants`, icon: <UsersRound/> }] },
  { label: "资源目录", items: [
    { label: "模型与服务", href: `${OMS_BASE}/services`, icon: <Blocks/> },
    { label: "供应商连接", href: `${OMS_BASE}/connections`, icon: <Link2/> },
    { label: "Agent 与能力", href: `${OMS_BASE}/agents`, icon: <Layers3/> },
    { label: "工具与集成", href: `${OMS_BASE}/tools`, icon: <Network/> },
    { label: "Skills", href: `${OMS_BASE}/skills`, icon: <Sparkles/> },
    { label: "知识基础能力", href: `${OMS_BASE}/knowledge`, icon: <LibraryBig/> },
    { label: "运行资源", href: `${OMS_BASE}/runtime`, icon: <CloudCog/> },
  ] },
  { label: "资源供给", items: [{ label: "服务供给", href: `${OMS_BASE}/supply`, icon: <PackageCheck/> }] },
  { label: "用量与运行", items: [{ label: "用量与运行", href: `${OMS_BASE}/usage`, icon: <Activity/> }] },
  { label: "审计与治理", items: [
    { label: "审计与治理", href: `${OMS_BASE}/audit`, icon: <ScrollText/> },
    { label: "平台人员", href: `${OMS_BASE}/platform-people`, icon: <UsersRound/> },
    { label: "角色与动作", href: `${OMS_BASE}/platform-roles`, icon: <Layers3/> },
    { label: "平台人员学校范围", href: `${OMS_BASE}/school-permissions`, icon: <ShieldCheck/> },
    { label: "授权审计", href: `${OMS_BASE}/authz-audit`, icon: <ScrollText/> },
  ] },
];

type OmsModel = {
  me: OmsMe;
  permissions: OmsPermissions;
  skills: OmsSkill[];
  models: OmsModelItem[];
  modelDraftVersion: number;
  modelDraftStatus: StatusLike;
  providerConnections: ProviderConnection[];
  providerStatus: StatusLike;
  providerSettingsVersion: number;
  resources: OmsResource[];
  summary: OmsSummary;
  schools: OmsSchoolProjection[];
  supplyDefinitions: OmsSupplyDefinition[];
  supplyLots: OmsSupplyLot[];
  quotaSummary: OmsQuotaSummary;
  auditEvents: OmsAuditEvent[];
  cost: OmsCostProjection;
  usageDetails: OmsUsageAttempt[];
  jobs: OmsJob[];
  inspectedSchoolId: string;
  authzCatalog: OmsPermissionCatalog;
  approvals: OmsApproval[];
  statusCatalog: OmsStatusCatalog;
};

async function fetchWithTimeout(path: string, init: RequestInit): Promise<Response> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new Error("request timeout"));
    }, REQUEST_TIMEOUT_MS);
  });
  try {
    return await Promise.race([
      fetch(path, { ...init, signal: controller.signal }),
      timeout,
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function refreshOmsSession() {
  const csrf = cookieValue("dt_oms_csrf");
  const response = await fetchWithTimeout("/api/v1/oms/auth/refresh", {
    method: "POST",
    credentials: "include",
    headers: { accept: "application/json", ...(csrf ? { "x-csrf-token": csrf } : {}) },
  });
  if (!response.ok) throw { status: response.status, detail: "oms session refresh failed" } satisfies ApiError;
}

async function readJson<T>(path: string, retryOnUnauthorized = true): Promise<T> {
  const response = await fetchWithTimeout(path, { credentials: "include", headers: { accept: "application/json" } });
  let body: unknown = {};
  try { body = await response.json(); } catch { body = {}; }
  if (response.status === 401 && retryOnUnauthorized) {
    // `dt_oms_refresh` 是 HttpOnly 且 Path=/api/v1/oms，前端不可读取；
    // 根路径可见的 CSRF cookie 是同一会话的非敏感 refresh hint。
    if (!cookieValue("dt_oms_csrf")) {
      const detail = typeof body === "object" && body && "detail" in body ? String((body as { detail?: unknown }).detail) : response.statusText;
      throw { status: response.status, detail, path } satisfies ApiError;
    }
    await refreshOmsSession();
    return readJson<T>(path, false);
  }
  if (!response.ok) {
    const detail = typeof body === "object" && body && "detail" in body ? String((body as { detail?: unknown }).detail) : response.statusText;
    throw { status: response.status, detail, path } satisfies ApiError;
  }
  return body as T;
}

async function readOptionalJson<T>(path: string, fallback: T): Promise<T> {
  try {
    return await readJson<T>(path);
  } catch {
    return fallback;
  }
}

function cookieValue(name: string) {
  if (typeof document === "undefined") return "";
  const prefix = `${name}=`;
  return document.cookie.split(";").map(item => item.trim()).find(item => item.startsWith(prefix))?.slice(prefix.length) ?? "";
}

async function writeJson<T>(path: string, body: Record<string, unknown>, method = "POST"): Promise<T> {
  const csrf = cookieValue("dt_oms_csrf");
  const response = await fetch(path, {
    method,
    credentials: "include",
    headers: { accept: "application/json", "content-type": "application/json", ...(csrf ? { "x-csrf-token": csrf } : {}) },
    body: JSON.stringify(body),
  });
  let data: unknown = {};
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) {
    const detail = typeof data === "object" && data && "detail" in data ? String((data as { detail?: unknown }).detail) : response.statusText;
    throw { status: response.status, detail, path } satisfies ApiError;
  }
  return data as T;
}

function blockedMessage(error?: ApiError) {
  const suffix = error ? `（${error.status} ${error.detail}）` : "";
  return `eduplus-platform-admin 授权码登录、账号状态或 ops.* 本地授权未通过${suffix}。`;
}

function toApiError(error: unknown): ApiError {
  if (typeof error === "object" && error !== null && "status" in error && "detail" in error) {
    const apiError = error as { status?: unknown; detail?: unknown; path?: unknown };
    const status = Number(apiError.status);
    return {
      status: Number.isFinite(status) ? status : 0,
      detail: String(apiError.detail ?? "request failed"),
      path: typeof apiError.path === "string" ? apiError.path : undefined,
    };
  }
  return { status: 0, detail: error instanceof Error ? error.message : String(error || "request failed") };
}

function isJsonRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseJsonRecord(text: string, label: string): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (caught) {
    throw new Error(`${label} 不是有效 JSON：${caught instanceof Error ? caught.message : String(caught)}`);
  }
  if (!isJsonRecord(value)) throw new Error(`${label} 必须是 JSON 对象。`);
  return value;
}

function parseJsonArray(text: string, label: string): unknown[] {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (caught) {
    throw new Error(`${label} 不是有效 JSON：${caught instanceof Error ? caught.message : String(caught)}`);
  }
  if (!Array.isArray(value)) throw new Error(`${label} 必须是 JSON 数组。`);
  return value;
}

function envSecretReference(seed: string) {
  const key = seed.trim().replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").toUpperCase() || "PROVIDER";
  return `env:${key}_API_KEY`;
}

function defaultModelDraftJson(rows: (OmsModelItem & { id: string })[]) {
  const draftRows = rows.length ? rows.map(row => ({
    profile_id: row.profile_id ?? `${row.provider ?? "provider"}-default`,
    model_id: row.model_id ?? row.model ?? row.id,
    model: row.model ?? row.model_id ?? row.id,
    provider: row.provider ?? "openai",
    base_url: "https://provider.example/v1",
    secret: envSecretReference(row.provider ?? row.profile_id ?? row.id),
  })) : [{
    profile_id: "chat",
    model_id: "qwen-plus",
    model: "qwen-plus",
    provider: "openai",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    secret: "env:DASHSCOPE_API_KEY",
    max_tokens: 4096,
    context_window: 32768,
  }];
  return JSON.stringify(draftRows, null, 2);
}

function defaultProviderSettingsJson(connection?: ProviderConnection) {
  const id = connection?.id ?? "dashscope";
  const provider = connection?.provider ?? id;
  const baseUrl = connection?.base_url ?? "https://dashscope.aliyuncs.com/compatible-mode/v1";
  return JSON.stringify({
    connections: {
      [id]: {
        provider,
        base_url: baseUrl,
        api_key: envSecretReference(provider),
      },
    },
  }, null, 2);
}

function permissionActions(permissions: OmsPermissions) {
  return Array.from(new Set([
    ...(permissions.actions ?? []),
    ...(permissions.platform_actions ?? []),
    ...(permissions.school_actions ?? []).flatMap(item => item.actions ?? []),
  ])).sort();
}

function platformPermissionActions(permissions: OmsPermissions) {
  return Array.from(new Set([
    ...(permissions.actions ?? []),
    ...(permissions.platform_actions ?? []),
  ])).sort();
}

function statusText(status?: StatusLike) {
  if (!status) return "unknown";
  if (typeof status === "string") return status;
  return status.label ?? status.code ?? "unknown";
}

function statusCode(status?: StatusLike) {
  if (!status) return "";
  return typeof status === "string" ? status : status.code ?? "";
}

function statusDescriptor(status: StatusLike | undefined, catalog?: OmsStatusCatalog) {
  const code = statusCode(status);
  if (!code) return undefined;
  return catalog?.statuses?.find(item => item.code === code);
}

function hasStatusCatalog(catalog?: OmsStatusCatalog) {
  return Boolean(catalog?.statuses?.length);
}

function statusLabel(status?: StatusLike, catalog?: OmsStatusCatalog) {
  if (!status) return "unknown";
  if (typeof status !== "string" && status.label) return status.label;
  const descriptor = statusDescriptor(status, catalog);
  if (descriptor?.label) return descriptor.label;
  if (hasStatusCatalog(catalog)) return "状态说明缺失，请联系支持";
  return statusText(status);
}

function statusDescription(status?: StatusLike, catalog?: OmsStatusCatalog) {
  if (!status) return "";
  if (typeof status !== "string" && status.description) return status.description;
  const descriptor = statusDescriptor(status, catalog);
  if (descriptor?.description) return descriptor.description;
  if (hasStatusCatalog(catalog)) return "后端未登记该状态的展示语义；前端不得硬编码 raw code。";
  return "";
}

function statusNoticeTone(status?: StatusLike, catalog?: OmsStatusCatalog): "info" | "warn" | "bad" {
  const tone = (typeof status === "string" ? undefined : status?.tone) ?? statusDescriptor(status, catalog)?.tone;
  if (tone === "danger") return "bad";
  if (tone === "warning") return "warn";
  return "info";
}

function statusCountSummary(rows?: OmsSchoolStatusCount[], catalog?: OmsStatusCatalog) {
  return rows?.length ? rows.map(row => `${statusLabel(row.status, catalog)} × ${row.count ?? 0}`).join("、") : "未返回";
}

function quotaGrantSummary(rows?: OmsSchoolQuotaGrantSummary[], catalog?: OmsStatusCatalog) {
  return rows?.length ? rows.map(row => `${statusLabel(row.status, catalog)} ${row.units ?? "0"}`).join("、") : "未返回";
}

function usageSummary(rows?: OmsSchoolUsageSummary[], catalog?: OmsStatusCatalog) {
  return rows?.length ? rows.map(row => `${statusLabel(row.status, catalog)} ${row.attempts ?? 0} 次 / ${row.settled_units ?? "0"}`).join("、") : "未返回";
}

function schoolDisplayName(school: Pick<OmsSchoolProjection, "school_name" | "school_code" | "school_id"> & { id?: string }) {
  const name = school.school_name?.trim();
  const code = school.school_code?.trim();
  return name || code || school.school_id || school.id || "未命名学校";
}

function schoolListName(school: Pick<OmsSchoolProjection, "school_name">) {
  return school.school_name?.trim() || "未返回";
}

function schoolListCode(school: Pick<OmsSchoolProjection, "school_code">) {
  const code = school.school_code?.trim();
  return code || "未返回";
}

const RESOURCE_CATEGORY_BY_ROOT: Record<string, string> = {
  services: "model_external",
  agents: "agent_capability",
  tools: "tool_integration",
  knowledge: "knowledge_content",
  runtime: "runtime",
};

const SERVICE_COPY: Record<string, Pick<ServiceView, "name" | "category" | "unit" | "description">> = {
  llm: { name: "对话模型", category: "模型服务", unit: "token", description: "面向智能体对话、推理与生成的模型服务。" },
  task: { name: "任务模型", category: "模型服务", unit: "token", description: "面向后台任务和批处理的模型服务。" },
  embedding: { name: "向量服务", category: "模型服务", unit: "vector", description: "面向检索、召回与语义索引的向量化服务。" },
  tts: { name: "语音合成", category: "模型服务", unit: "character", description: "面向语音输出的文本转语音服务。" },
  stt: { name: "语音识别", category: "模型服务", unit: "second", description: "面向语音输入的语音转文本服务。" },
  imagegen: { name: "图片生成", category: "模型服务", unit: "image", description: "面向图片生成与编辑的多模态服务。" },
  videogen: { name: "视频生成", category: "模型服务", unit: "video", description: "面向视频生成与编辑的多模态服务。" },
  search: { name: "联网搜索", category: "工具服务", unit: "request", description: "面向联网检索与事实核验的搜索服务。" },
  ocr: { name: "文档识别", category: "知识处理", unit: "page", description: "面向文档 OCR、版面识别与结构化抽取的解析服务。" },
  rag: { name: "知识检索", category: "知识处理", unit: "query", description: "面向知识库检索、引用与图检索的服务。" },
};

const PROFILE_SERVICE_IDS = new Set(["llm", "task", "embedding", "tts", "stt", "imagegen", "videogen", "search", "ocr", "rag"]);
const MODEL_SERVICE_IDS = new Set(["llm", "task", "embedding", "tts", "stt", "imagegen", "videogen"]);
const CONNECTABLE_SERVICE_IDS = new Set(["llm", "task", "embedding", "tts", "stt", "imagegen", "videogen"]);
const DOCUMENT_SERVICE_IDS = new Set(["ocr", "rag"]);
const MODEL_PROFILE_TO_SERVICE: Record<string, string> = {
  chat: "llm",
  llm: "llm",
  task: "task",
  embedding: "embedding",
  text_embedding: "embedding",
  tts: "tts",
  stt: "stt",
  speech: "stt",
  image: "imagegen",
  imagegen: "imagegen",
  video: "videogen",
  videogen: "videogen",
  search: "search",
  ocr: "ocr",
  rag: "rag",
};

function resourceRowsForRoot(root: string, rows: OmsResource[]) {
  const category = RESOURCE_CATEGORY_BY_ROOT[root];
  if (!category) return rows;
  return rows.filter(row => row.category === category);
}

function resourceEmptyText(root: string) {
  if (root === "knowledge") return "知识基础能力正式 DTO 未返回；当前不会回退到原型合成知识库或私有正文。";
  if (root === "agents") return "Agent 与能力正式 DTO 未返回；当前不会回退到原型合成能力。";
  if (root === "tools") return "工具与集成正式 DTO 未返回；当前不会回退到原型合成工具。";
  if (root === "services") return "模型与服务正式 DTO 未返回；当前不会回退到部署外合成模型。";
  if (root === "runtime") return "运行资源正式 DTO 未返回；当前不会回退到原型运行资源。";
  return "未返回可见平台资源安全 DTO。";
}

function serviceIdFromModel(row: OmsModelItem) {
  const profile = row.profile_id?.trim().toLowerCase();
  if (profile && MODEL_PROFILE_TO_SERVICE[profile]) return MODEL_PROFILE_TO_SERVICE[profile];
  const modelId = (row.model_id ?? row.model ?? "").toLowerCase();
  if (modelId.includes("embedding") || modelId.includes("embed")) return "embedding";
  if (modelId.includes("tts")) return "tts";
  if (modelId.includes("stt") || modelId.includes("speech")) return "stt";
  if (modelId.includes("image") || modelId.includes("wanx")) return "imagegen";
  if (modelId.includes("video") || modelId.includes("wan-")) return "videogen";
  return "llm";
}

function serviceIdFromResource(row: OmsResource) {
  const safeServiceId = row.safe_fields?.service_id;
  if (typeof safeServiceId === "string" && safeServiceId.trim()) return safeServiceId.trim();
  const kind = row.kind?.trim().toLowerCase();
  if (kind && MODEL_PROFILE_TO_SERVICE[kind]) return MODEL_PROFILE_TO_SERVICE[kind];
  const id = row.id.toLowerCase();
  if (id.includes("embedding") || id.includes("embed")) return "embedding";
  if (id.includes("ocr")) return "ocr";
  if (id.includes("rag") || id.includes("knowledge")) return "rag";
  if (id.includes("search")) return "search";
  if (id.includes("tts")) return "tts";
  if (id.includes("stt") || id.includes("speech")) return "stt";
  if (id.includes("image")) return "imagegen";
  if (id.includes("video")) return "videogen";
  if (id.includes("model") || id.includes("chat") || id.includes("llm")) return "llm";
  return "";
}

function serviceStatusFromStatus(status?: StatusLike, enabled = true): ServiceView["status"] {
  if (!enabled) return "unavailable";
  const code = statusCode(status).toLowerCase();
  if (!code) return "limited";
  if (["active", "allow", "allowed", "available", "enabled", "ok", "published", "ready", "settled", "success", "tested", "verified"].includes(code)) return "available";
  if (["blocked", "deny", "disabled", "error", "failed", "forbidden", "not_configured", "revoked", "unavailable"].includes(code)) return "unavailable";
  return "limited";
}

function serviceStatusRank(status: ServiceView["status"]) {
  return status === "unavailable" ? 3 : status === "limited" ? 2 : 1;
}

function mergeServiceStatus(current: ServiceView["status"], next: ServiceView["status"]) {
  return serviceStatusRank(next) > serviceStatusRank(current) ? next : current;
}

function serviceBase(serviceId: string): OmsServiceRow {
  const copy = SERVICE_COPY[serviceId] ?? {
    name: serviceId,
    category: "平台服务",
    unit: "unit",
    description: "后端正式 DTO 返回的服务目录项。",
  };
  return {
    id: serviceId,
    ...copy,
    status: "limited",
    source: "正式 DTO",
  };
}

function buildServiceRows(
  supplyDefinitions: OmsSupplyDefinition[],
  modelRows: OmsModelItem[],
  resourceRows: OmsResource[],
) {
  const byId = new Map<string, OmsServiceRow>();
  const upsert = (serviceId: string, patch: Partial<OmsServiceRow>) => {
    if (!serviceId) return;
    const current = byId.get(serviceId) ?? serviceBase(serviceId);
    byId.set(serviceId, {
      ...current,
      ...patch,
      id: serviceId,
      status: patch.status ? mergeServiceStatus(current.status, patch.status) : current.status,
      description: patch.description ?? current.description,
      source: [current.source, patch.source].filter(Boolean).join(" / "),
    });
  };
  for (const definition of supplyDefinitions) {
    const serviceId = definition.service_id?.trim();
    if (!serviceId) continue;
    const copy = SERVICE_COPY[serviceId];
    upsert(serviceId, {
      name: copy?.name ?? serviceId,
      category: copy?.category ?? (definition.resource_category === "model_external" ? "模型服务" : "平台服务"),
      unit: definition.unit_code ?? copy?.unit ?? "unit",
      status: serviceStatusFromStatus(definition.enabled ? "enabled" : "disabled", definition.enabled),
      rawStatus: definition.enabled ? "enabled" : "disabled",
      source: "服务供给 DTO",
      description: copy?.description ?? "OMS supply DTO 返回的服务定义。",
    });
  }
  for (const item of modelRows) {
    const serviceId = serviceIdFromModel(item);
    const copy = SERVICE_COPY[serviceId];
    upsert(serviceId, {
      name: copy?.name ?? item.profile_id ?? serviceId,
      category: copy?.category ?? "模型服务",
      unit: copy?.unit ?? "token",
      status: serviceStatusFromStatus(item.status),
      rawStatus: item.status,
      source: item.source ?? "模型草稿 DTO",
      description: copy?.description ?? "OMS model draft DTO 返回的模型服务。",
    });
  }
  for (const resource of resourceRows.filter(row => row.category === RESOURCE_CATEGORY_BY_ROOT.services)) {
    const serviceId = serviceIdFromResource(resource);
    if (!serviceId) continue;
    const copy = SERVICE_COPY[serviceId];
    upsert(serviceId, {
      name: copy?.name ?? resource.display_name ?? serviceId,
      category: copy?.category ?? resource.kind ?? "平台服务",
      unit: typeof resource.safe_fields?.unit_code === "string" ? resource.safe_fields.unit_code : copy?.unit ?? "unit",
      status: serviceStatusFromStatus(resource.status, resource.managed !== false),
      rawStatus: resource.status,
      source: "资源状态 DTO",
      description: copy?.description ?? resource.display_name ?? "OMS resources/status DTO 返回的服务状态。",
    });
  }
  return Array.from(byId.values()).sort((left, right) => left.name.localeCompare(right.name, "zh-Hans-CN"));
}

const SENSITIVE_SAFE_FIELD = /secret|token|password|api[_-]?key|credential/i;
const SENSITIVE_SAFE_VALUE = /(^sk-|bearer\s+|^env:)/i;

function safeFieldRows(resource: OmsResource) {
  return Object.entries(resource.safe_fields ?? {})
    .filter(([key, value]) => {
      if (SENSITIVE_SAFE_FIELD.test(key)) return false;
      if (typeof value === "string" && SENSITIVE_SAFE_VALUE.test(value)) return false;
      return true;
    })
    .map(([key, value]) => ({
      label: key,
      value: safeFieldValue(value),
    }));
}

function safeFieldValue(value: unknown): ReactNode {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(item => safeFieldValue(item)).join("、") || "—";
  return "结构化 descriptor";
}

function redactedCredentialLabel() {
  // Provider 设置可能返回后端占位符、Secret 引用或旧接口残留字段；
  // OMS 前端一律只展示脱敏标记，避免把 env ref / sk-* 当成普通文本泄露。
  return "<redacted>";
}

function commandId() {
  return globalThis.crypto?.randomUUID?.() ?? "00000000-0000-4000-8000-000000000001";
}

function farFutureIso() {
  return "9998-01-01T00:00:00Z";
}

function currentOmsPath() {
  if (typeof window === "undefined") return OMS_BASE;
  const pathname = window.location.pathname;
  return pathname === OMS_BASE || pathname.startsWith(`${OMS_BASE}/`) ? pathname : OMS_BASE;
}

function omsRoot(path: string) {
  if (path === OMS_BASE) return "home";
  return path.slice(OMS_BASE.length).split("/").filter(Boolean)[0] ?? "home";
}

function omsSegments(path: string) {
  return path === OMS_BASE ? [] : path.slice(OMS_BASE.length).split("/").filter(Boolean).map(segment => {
    try { return decodeURIComponent(segment); } catch { return segment; }
  });
}

function routeUsageSchoolId(path: string) {
  const segments = omsSegments(path);
  return segments[0] === "usage" && segments[1] === "school" ? segments[2] ?? "" : "";
}

function encodeRoutePart(value: string) {
  return encodeURIComponent(value);
}

function omsLoginHref() {
  if (typeof window === "undefined") return "/api/v1/oms/auth/start";
  return `/api/v1/oms/auth/start?return_to=${encodeURIComponent(window.location.href)}`;
}

function beginOmsLogin() {
  if (typeof window === "undefined") return;
  window.location.href = omsLoginHref();
}

export default function OmsFormalApp() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<ApiError | undefined>();
  const [model, setModel] = useState<OmsModel | undefined>();
  const [commandMessage, setCommandMessage] = useState("");
  const [bootstrapMessage, setBootstrapMessage] = useState("");
  const [route, setRoute] = useState(currentOmsPath);
  const [catalogTab, setCatalogTab] = useState("全部服务");
  const [formOpen, setFormOpen] = useState<OmsFormKey>("");
  const [modelDraftJson, setModelDraftJson] = useState("");
  const [providerSettingsJson, setProviderSettingsJson] = useState("");
  const [formError, setFormError] = useState("");
  const selectedUsageSchoolId = routeUsageSchoolId(route);

  useEffect(() => {
    const onPopState = () => setRoute(currentOmsPath());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = (href: string) => {
    setRoute(href);
    if (typeof window !== "undefined" && window.location.pathname !== href) {
      window.history.pushState(null, "", href);
    }
  };
  const shell = (children: ReactNode, scope = "正式受控入口") => <AdminShell
    product="OMS"
    subtitle="平台智能体运营后台"
    scope={scope}
    groups={OMS_NAV}
    path={route}
    onNavigate={navigate}
    environmentLabel="正式受控入口"
    footerLabel="正式入口 · 安全 DTO"
    mainLabel="OMS 正式管理入口"
  >
    {children}
  </AdminShell>;

  const bootstrapFirstAdmin = async () => {
    setBootstrapMessage("正在自动完成首位 OMS 管理员本地授权初始化…");
    await writeJson("/api/v1/oms/bootstrap/first-admin", {
      command_id: commandId(),
      reason: "OMS 首位平台管理员自动初始化",
    });
    setBootstrapMessage("首位 OMS 管理员已初始化，正在重新读取正式入口。");
  };

  useEffect(() => {
    let cancelled = false;
    async function load(bootstrapAttempted = false) {
      setState("loading");
      if (!bootstrapAttempted) setBootstrapMessage("");
      try {
        const me = await readJson<OmsMe>("/api/v1/oms/me");
        const permissions = await readJson<OmsPermissions>("/api/v1/oms/me/permissions");
        const actions = permissionActions(permissions);
        const platformActions = platformPermissionActions(permissions);
        const statusCatalog = actions.includes("ops.oms.access")
          ? await readOptionalJson<OmsStatusCatalog>("/api/v1/oms/status/catalog", { statuses: [] })
          : { statuses: [] };
        const authzCatalog = platformActions.includes("ops.permissions.manage")
          ? await readJson<OmsPermissionCatalog>("/api/v1/oms/permissions")
          : { roles: [], principals: [], assignments: [] };
        const approvals = platformActions.includes("ops.permissions.manage")
          ? await readJson<{ approvals?: OmsApproval[] }>("/api/v1/oms/approvals")
          : { approvals: [] };
        const skillsResult = platformActions.includes("ops.skills.read")
          ? await readJson<{ skills?: OmsSkill[] }>("/api/v1/oms/skills")
          : { skills: [] };
        const modelDraft = platformActions.includes("ops.providers.read")
          ? await readJson<{ version?: number; status?: StatusLike; models?: OmsModelItem[] }>("/api/v1/oms/models/draft")
          : { version: 0, status: "not_loaded", models: [] };
        const providerSettings = platformActions.includes("ops.providers.read")
          ? await readJson<{ version?: number; status?: StatusLike; settings?: { connections?: Record<string, Omit<ProviderConnection, "id">> } }>("/api/v1/oms/provider-settings")
          : { version: 0, status: "not_loaded", settings: { connections: {} } };
        const resourceStatus = platformActions.includes("ops.providers.read")
          ? await readJson<{ resources?: OmsResource[] }>("/api/v1/oms/resources/status")
          : { resources: [] };
        const summary = actions.includes("ops.oms.access")
          ? await readJson<OmsSummary>("/api/v1/oms/summary")
          : {};
        const schools = actions.includes("ops.tenants.read")
          ? await readJson<{ tenants?: OmsSchoolProjection[] }>("/api/v1/oms/tenants")
          : { tenants: [] };
        const tenantRows = schools.tenants ?? [];
        const inspectedSchoolId = selectedUsageSchoolId && tenantRows.some(item => item.school_id === selectedUsageSchoolId)
          ? selectedUsageSchoolId
          : tenantRows.find(item => item.school_id)?.school_id ?? "";
        const inspectedSchoolPath = inspectedSchoolId ? encodeURIComponent(inspectedSchoolId) : "";
        const usage = actions.includes("ops.usage.read") && inspectedSchoolPath
          ? await readJson<{ details?: OmsUsageAttempt[] }>(`/api/v1/oms/schools/${inspectedSchoolPath}/usage`)
          : { details: [] };
        const jobs = actions.includes("ops.jobs.read") && inspectedSchoolPath
          ? await readJson<{ jobs?: OmsJob[] }>(`/api/v1/oms/schools/${inspectedSchoolPath}/jobs`)
          : { jobs: [] };
        const supply = platformActions.includes("ops.supply.read")
          ? await readJson<{ service_definitions?: OmsSupplyDefinition[]; supply_lots?: OmsSupplyLot[] }>("/api/v1/oms/supply")
          : { service_definitions: [], supply_lots: [] };
        const quotaSummary = actions.includes("ops.quotas.read") && actions.includes("ops.entitlements.read") && inspectedSchoolPath
          ? await readJson<OmsQuotaSummary>(`/api/v1/oms/schools/${inspectedSchoolPath}/quota`)
          : { entitlements: [], grants: [] };
        const audit = platformActions.includes("ops.audit.read")
          ? await readJson<{ management_events?: OmsAuditEvent[]; oms_events?: OmsAuditEvent[] }>("/api/v1/oms/audit")
          : actions.includes("ops.audit.read") && inspectedSchoolPath
            ? await readJson<{ management_events?: OmsAuditEvent[]; oms_events?: OmsAuditEvent[] }>(`/api/v1/oms/audit?school_id=${inspectedSchoolPath}`)
            : { management_events: [], oms_events: [] };
        const cost = platformActions.includes("ops.cost.read")
          ? await readJson<OmsCostProjection>("/api/v1/oms/cost")
          : {};
        const connections = Object.entries(providerSettings.settings?.connections ?? {}).map(([id, value]) => ({
          id,
          provider: value.provider,
          base_url: value.base_url,
          api_key: value.api_key ? "<redacted>" : undefined,
        }));
        if (!cancelled) {
          setModel({
            me,
            permissions,
            skills: skillsResult.skills ?? [],
            models: modelDraft.models ?? [],
            modelDraftVersion: modelDraft.version ?? 0,
            modelDraftStatus: modelDraft.status ?? "unknown",
            providerConnections: connections,
            providerStatus: providerSettings.status ?? "unknown",
            providerSettingsVersion: providerSettings.version ?? 0,
            resources: resourceStatus.resources ?? [],
            summary,
            schools: tenantRows,
            supplyDefinitions: supply.service_definitions ?? [],
            supplyLots: supply.supply_lots ?? [],
            quotaSummary,
            auditEvents: [...(audit.management_events ?? []), ...(audit.oms_events ?? [])],
            cost,
            usageDetails: usage.details ?? [],
            jobs: jobs.jobs ?? [],
            inspectedSchoolId,
            authzCatalog,
            approvals: approvals.approvals ?? [],
            statusCatalog,
          });
          setState("ready");
        }
      } catch (caught) {
        if (!cancelled) {
          const detail = toApiError(caught);
          setError(detail);
          if (detail.status === 401) {
            setState("redirecting");
            beginOmsLogin();
            return;
          }
          if (
            detail.status === 403
            && detail.path === "/api/v1/oms/me"
            && !bootstrapAttempted
          ) {
            try {
              await bootstrapFirstAdmin();
              if (!cancelled) await load(true);
              return;
            } catch (bootstrapCaught) {
              const bootstrapDetail = toApiError(bootstrapCaught);
              setError(bootstrapDetail.status === 409 ? detail : bootstrapDetail);
              setBootstrapMessage(
                bootstrapDetail.status === 409
                  ? "当前环境已存在 OMS 管理员，本账号未获得本地 ops.* 授权。"
                  : `首位 OMS 管理员自动初始化未完成：${bootstrapDetail.status} ${bootstrapDetail.detail}`,
              );
              setState("blocked");
              return;
            }
          }
          setState("blocked");
        }
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [selectedUsageSchoolId]);

  if (state === "loading") return shell(<>
    <StatePanel state="loading" message="正在读取正式 OMS 安全 DTO。"/>
    {bootstrapMessage && <Notice tone="info">{bootstrapMessage}</Notice>}
  </>);
  if (state === "redirecting") return shell(<StatePanel state="loading" message="正在跳转到 eduplus-platform-admin 登录"/>);

  if (state === "blocked") {
    const denied = error?.status === 403;
    return shell(<>
      <PageHead title={denied ? "无权访问 OMS" : "OMS 暂不可用"} description={blockedMessage(error)}/>
      <Notice tone={denied ? "warn" : "bad"}>
        {denied
          ? "当前账号已完成 eduplus-platform-admin 登录，但尚未获得 DeepTutor Enterprise 本地 ops.* 授权。"
          : "OMS 无法确认当前会话或读取正式后台数据；请稍后重试。"}
      </Notice>
      {bootstrapMessage && <Notice tone={bootstrapMessage.includes("未完成") ? "bad" : "info"}>{bootstrapMessage}</Notice>}
      <div className="inline-list">
        <Button onClick={beginOmsLogin}>重新登录 eduplus-platform-admin</Button>
      </div>
    </>);
  }

  const actions = model ? permissionActions(model.permissions) : [];
  const platformActions = model ? platformPermissionActions(model.permissions) : [];
  const modelRows = (model?.models ?? []).map((item, index) => ({ ...item, id: item.id ?? `${item.profile_id ?? "profile"}:${item.model_id ?? index}` }));
  const providerRows = model?.providerConnections ?? [];
  const resourceRows = model?.resources ?? [];
  const schoolRows = (model?.schools ?? []).map((school, index) => ({ ...school, id: school.school_id ?? `school-${index}` }));
  const supplyDefinitionRows = (model?.supplyDefinitions ?? []).map((definition, index) => ({ ...definition, id: definition.service_id ?? `service-${index}` }));
  const supplyLotRows = (model?.supplyLots ?? []).map((lot, index) => ({ ...lot, id: lot.lot_id ?? lot.id ?? `${lot.service_id ?? "service"}:${lot.pool_id ?? index}` }));
  const entitlementRows = (model?.quotaSummary.entitlements ?? []).map((entitlement, index) => ({ ...entitlement, id: entitlement.service_id ?? `entitlement-${index}` }));
  const quotaGrantRows = (model?.quotaSummary.grants ?? []).map((grant, index) => ({ ...grant, id: grant.grant_id ?? `quota-grant-${index}` }));
  const auditRows = (model?.auditEvents ?? []).map((event, index) => ({ ...event, id: event.id ?? event.request_id ?? `audit-${index}` }));
  const usageRows = (model?.usageDetails ?? []).map((attempt, index) => ({ ...attempt, id: attempt.attempt_id ?? `usage-${index}` }));
  const jobRows = (model?.jobs ?? []).map((job, index) => ({ ...job, id: job.attempt_id ?? `job-${index}` }));
  const skillRows = (model?.skills ?? []).map((skill, index) => ({
    ...skill,
    id: skill.id ?? skill.revision_id ?? skill.name ?? `skill-${index}`,
  }));
  const authzPrincipalRows = (model?.authzCatalog?.principals ?? []).map((principal, index) => ({
    ...principal,
    id: principal.id ?? principal.principal_id ?? `principal-${index}`,
  }));
  const authzRoleRows = (model?.authzCatalog?.roles ?? []).map((role, index) => ({
    ...role,
    id: role.id ?? `${role.role_key ?? "role"}:${role.version ?? index}`,
  }));
  const authzAssignmentRows = (model?.authzCatalog?.assignments ?? []).map((assignment, index) => ({
    ...assignment,
    id: assignment.id ?? assignment.assignment_id ?? `assignment-${index}`,
  }));
  const approvalRows = (model?.approvals ?? []).map((approval, index) => ({
    ...approval,
    id: approval.id ?? approval.approval_id ?? `approval-${index}`,
  }));
  const serviceRows = buildServiceRows(supplyDefinitionRows, modelRows, resourceRows);
  const canManageProviders = platformActions.includes("ops.providers.manage");
  const canReviewSkills = platformActions.includes("ops.skills.review");
  const canPublishSkills = platformActions.includes("ops.skills.publish");
  const canGrantSkills = actions.includes("ops.skills.grant");
  const canManagePermissions = platformActions.includes("ops.permissions.manage");
  const canManageSupply = platformActions.includes("ops.supply.manage");
  const canManageEntitlements = actions.includes("ops.entitlements.manage");
  const canManageQuotas = actions.includes("ops.quotas.manage");
  const configRole = authzRoleRows.find(row => row.role_key === "platform_config_admin");
  const schoolAuditRole = authzRoleRows.find(row => row.role_key === "platform_auditor");
  const reason = "正式 OMS 受控操作";
  const runCommand = async (label: string, path: string, body: Record<string, unknown>, method = "POST") => {
    setCommandMessage(`${label} 已提交，等待审计回读。`);
    try {
      await writeJson(path, body, method);
      setCommandMessage(`${label} 已提交；请在审计区按 request_id 回读确认。`);
      return true;
    } catch (caught) {
      const detail = toApiError(caught);
      setCommandMessage(`${label} 被拒绝：${detail.status} ${detail.detail}`);
      return false;
    }
  };
  const providerCommand = (path: string, label: string) => runCommand(label, path, {
    expected_version: model?.providerSettingsVersion ?? 0,
    reason,
  });
  const modelCommand = (path: string, label: string) => runCommand(label, path, {
    expected_version: model?.modelDraftVersion ?? 0,
    reason,
  });
  const openModelDraftJsonForm = () => {
    setFormError("");
    setModelDraftJson(defaultModelDraftJson(modelRows));
    setFormOpen("model-draft-json");
  };
  const openProviderSettingsJsonForm = (connection?: ProviderConnection) => {
    setFormError("");
    setProviderSettingsJson(defaultProviderSettingsJson(connection));
    setFormOpen("provider-settings-json");
  };
  const closeForm = () => {
    setFormError("");
    setFormOpen("");
  };
  const saveModelDraftJson = async () => {
    if (!canManageProviders) {
      setFormError("当前账号缺少 ops.providers.manage，不能保存模型草稿。");
      return;
    }
    let models: unknown[];
    try {
      models = parseJsonArray(modelDraftJson, "模型草稿 JSON");
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : String(caught));
      return;
    }
    setFormError("");
    const ok = await runCommand("保存模型草稿", "/api/v1/oms/models/draft", {
      expected_version: model?.modelDraftVersion ?? 0,
      reason,
      models,
    });
    if (ok) closeForm();
  };
  const dryRunProviderSettingsJson = async () => {
    let settings: Record<string, unknown>;
    try {
      settings = parseJsonRecord(providerSettingsJson, "Provider 设置 JSON");
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : String(caught));
      return;
    }
    setFormError("");
    try {
      await writeJson("/api/v1/oms/provider-settings/dry-run", {
        source_kind: "oms-formal-ui",
        settings,
      });
      setCommandMessage("Provider 设置 dry-run 完成；请确认 Secret 均为 env: 引用后保存草稿。");
    } catch (caught) {
      const detail = toApiError(caught);
      setCommandMessage(`Provider 设置 dry-run 被拒绝：${detail.status} ${detail.detail}`);
    }
  };
  const saveProviderSettingsJson = async () => {
    if (!canManageProviders) {
      setFormError("当前账号缺少 ops.providers.manage，不能保存 Provider 草稿。");
      return;
    }
    let settings: Record<string, unknown>;
    try {
      settings = parseJsonRecord(providerSettingsJson, "Provider 设置 JSON");
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : String(caught));
      return;
    }
    setFormError("");
    const ok = await runCommand("保存 Provider 草稿", "/api/v1/oms/provider-settings/draft", {
      expected_version: model?.providerSettingsVersion ?? 0,
      reason,
      settings,
    });
    if (ok) closeForm();
  };
  const entitlementCommand = (serviceId: string, status: "active" | "revoked", expectedVersion: number) => runCommand(
    status === "active" ? "授权当前学校服务" : "撤销当前学校服务授权",
    `/api/v1/oms/schools/${encodeURIComponent(model?.inspectedSchoolId ?? "")}/entitlements/${encodeURIComponent(serviceId)}`,
    {
      status,
      starts_at: "1970-01-01T00:00:00Z",
      expires_at: farFutureIso(),
      expected_version: expectedVersion,
      idempotency_key: commandId(),
      reason,
    },
  );
  const quotaGrantCommand = (entitlement: OmsServiceEntitlement) => {
    const serviceId = entitlement.service_id ?? "";
    const lot = supplyLotRows.find(item => item.service_id === serviceId && item.provider_id && item.pool_id);
    if (!lot || !serviceId) return;
    void runCommand("赠送当前学校额度", `/api/v1/oms/schools/${encodeURIComponent(model?.inspectedSchoolId ?? "")}/quota-grants`, {
      grant_id: commandId(),
      service_id: serviceId,
      unit_code: lot.unit_code ?? "unit",
      acquisition_method: "gift",
      quantity: "1",
      starts_at: "1970-01-01T00:00:00Z",
      expires_at: farFutureIso(),
      provider_id: lot.provider_id,
      pool_id: lot.pool_id,
      source_ref: "oms-formal-ui:gift",
      expected_entitlement_version: entitlement.version ?? 1,
      idempotency_key: commandId(),
      reason,
    });
  };
  const quotaAdjustCommand = (grant: OmsQuotaGrant) => runCommand(
    "调整当前额度",
    `/api/v1/oms/schools/${encodeURIComponent(model?.inspectedSchoolId ?? "")}/quota-grants/${encodeURIComponent(grant.grant_id ?? grant.id ?? "")}`,
    {
      expected_version: grant.version ?? 1,
      new_quantity: grant.quantity ?? "1",
      idempotency_key: commandId(),
      reason,
    },
    "PATCH",
  );
  const quotaCloseCommand = (label: string, grant: OmsQuotaGrant, action: "revoke" | "expire") => runCommand(
    label,
    `/api/v1/oms/schools/${encodeURIComponent(model?.inspectedSchoolId ?? "")}/quota-grants/${encodeURIComponent(grant.grant_id ?? grant.id ?? "")}/${action}`,
    {
      expected_version: grant.version ?? 1,
      idempotency_key: commandId(),
      reason,
    },
  );
  const supplyRevokeCommand = (lot: OmsSupplyLot) => {
    const lotId = lot.lot_id ?? lot.id ?? "";
    if (!lotId) return;
    void runCommand(
      "撤销供给批次",
      `/api/v1/oms/supply/lots/${encodeURIComponent(lotId)}/revoke`,
      {
        expected_version: lot.version ?? 1,
        reason,
      },
    );
  };
  const segments = omsSegments(route);
  const root = omsRoot(route);
  const detailRoot = segments[0] ?? "home";
  const usageSchoolId = detailRoot === "usage" && segments[1] === "school" ? segments[2] ?? "" : "";
  const detailId = detailRoot === "usage" && segments[1] === "school" ? segments[3] : segments[1];
  const serviceView = detailRoot === "services" ? segments[2] ?? "info" : "";
  const serviceItemId = detailRoot === "services" ? segments[3] : undefined;
  const visibleResourceRows = resourceRowsForRoot(root, resourceRows);
  const modelDraftStatusLabel = statusLabel(model?.modelDraftStatus, model?.statusCatalog);
  const providerSettingsStatusLabel = statusLabel(model?.providerStatus, model?.statusCatalog);
  const openDetail = (section: string, id: string) => navigate(`${OMS_BASE}/${section}/${encodeRoutePart(id)}`);
  const openServiceView = (serviceId: string, view: string, itemId?: string) => {
    navigate(`${OMS_BASE}/services/${encodeRoutePart(serviceId)}/${view}${itemId ? `/${encodeRoutePart(itemId)}` : ""}`);
  };
  const openModelDetail = (row: OmsModelItem & { id: string }) => openServiceView(serviceIdFromModel(row), "models", row.id);
  const connectionServiceIds = (connection: ProviderConnection) => {
    const provider = connection.provider ?? connection.id;
    return Array.from(new Set([
      ...modelRows.filter(row => row.provider === provider || row.provider === connection.id).map(serviceIdFromModel),
      ...supplyLotRows.filter(row => row.provider_id === provider || row.provider_id === connection.id).map(row => row.service_id ?? "").filter(Boolean),
    ])).filter(Boolean);
  };
  const connectionServiceScope = (connection: ProviderConnection) => {
    const serviceIds = connectionServiceIds(connection);
    return serviceIds.length
      ? serviceIds.map(serviceId => serviceRows.find(row => row.id === serviceId)?.name ?? SERVICE_COPY[serviceId]?.name ?? serviceId).join("、")
      : "正式 DTO 未返回适用服务";
  };
  const connectionCredentialStatus = (connection: ProviderConnection) => connection.api_key ? "已托管 · 明文不可见" : "后端未返回凭据状态";
  const profileRowsForService = (serviceId: string): OmsProfileRow[] => {
    const profiles = new Map<string, OmsProfileRow>();
    for (const row of modelRows.filter(item => serviceIdFromModel(item) === serviceId)) {
      const profileId = row.profile_id ?? `${row.provider ?? "provider"}:${serviceId}`;
      const key = `${profileId}:${row.provider ?? ""}`;
      const current = profiles.get(key);
      profiles.set(key, {
        id: profileId,
        profile_id: profileId,
        provider: row.provider,
        status: row.status,
        source: row.source,
        service_id: serviceId,
        model_count: (current?.model_count ?? 0) + 1,
      });
    }
    return Array.from(profiles.values());
  };
  const serviceActions = (row: ServiceView) => [
    { label: "服务概况", onClick: () => openServiceView(row.id, "info") },
    { label: "服务配置", onClick: () => openServiceView(row.id, "config") },
    ...(PROFILE_SERVICE_IDS.has(row.id) ? [{ label: "Provider 配置", onClick: () => openServiceView(row.id, "provider") }] : []),
    ...(MODEL_SERVICE_IDS.has(row.id) ? [{ label: "模型清单", onClick: () => openServiceView(row.id, "models") }] : []),
    { label: "关联记录", onClick: () => openServiceView(row.id, "relations") },
    { label: "发布记录", onClick: () => openServiceView(row.id, "release") },
  ];
  const openUsageDetail = (id: string) => {
    const schoolSegment = model?.inspectedSchoolId ? `/school/${encodeRoutePart(model.inspectedSchoolId)}` : "";
    navigate(`${OMS_BASE}/usage${schoolSegment}/${encodeRoutePart(id)}`);
  };
  const closeDetail = () => {
    if (detailRoot === "usage" && usageSchoolId) {
      navigate(`${OMS_BASE}/usage/school/${encodeRoutePart(usageSchoolId)}`);
      return;
    }
    if (detailRoot === "services" && detailId && serviceView && serviceItemId && ["models", "provider"].includes(serviceView)) {
      navigate(`${OMS_BASE}/services/${encodeRoutePart(detailId)}/${serviceView}`);
      return;
    }
    navigate(detailRoot === "home" ? OMS_BASE : `${OMS_BASE}/${detailRoot}`);
  };
  const detailTitle = (() => {
    if (!detailId) return "";
    if (detailRoot === "tenants") {
      const school = schoolRows.find(row => row.id === detailId || row.school_id === detailId);
      return school ? schoolDisplayName(school) : detailId;
    }
    if (detailRoot === "services") {
      const service = serviceRows.find(row => row.id === detailId);
      if (serviceItemId && serviceView === "models") {
        const modelItem = modelRows.find(row => row.id === serviceItemId);
        return modelItem?.model_id ?? modelItem?.model ?? service?.name ?? detailId;
      }
      if (serviceItemId && serviceView === "provider") {
        const profileItem = profileRowsForService(detailId).find(row => row.id === serviceItemId);
        return profileItem?.profile_id ?? service?.name ?? detailId;
      }
      return service?.name ?? modelRows.find(row => row.id === detailId)?.model_id ?? modelRows.find(row => row.id === detailId)?.model ?? detailId;
    }
    if (detailRoot === "connections") return providerRows.find(row => row.id === detailId)?.provider ?? detailId;
    if (detailRoot === "supply") return supplyDefinitionRows.find(row => row.id === detailId)?.service_id ?? supplyLotRows.find(row => row.id === detailId)?.service_id ?? detailId;
    if (detailRoot === "usage") return usageRows.find(row => row.id === detailId)?.attempt_id ?? jobRows.find(row => row.id === detailId)?.attempt_id ?? detailId;
    if (detailRoot === "audit") return auditRows.find(row => row.id === detailId)?.action ?? detailId;
    if (detailRoot === "platform-people") return authzPrincipalRows.find(row => row.id === detailId || row.principal_id === detailId)?.subject ?? detailId;
    if (detailRoot === "platform-roles") return authzRoleRows.find(row => row.id === detailId)?.role_key ?? detailId;
    if (detailRoot === "school-permissions") return authzAssignmentRows.find(row => row.id === detailId || row.assignment_id === detailId)?.role_key ?? detailId;
    if (detailRoot === "authz-audit") return approvalRows.find(row => row.id === detailId || row.approval_id === detailId)?.operation ?? auditRows.find(row => row.id === detailId || row.request_id === detailId)?.action ?? detailId;
    if (detailRoot === "skills") return skillRows.find(row => row.id === detailId)?.name ?? detailId;
    if (["agents", "tools", "knowledge", "runtime"].includes(detailRoot)) return resourceRows.find(row => row.id === detailId)?.display_name ?? detailId;
    return detailId;
  })();
  const detailContent = (() => {
    if (!detailId) return null;
    if (detailRoot === "tenants") {
      const school = schoolRows.find(row => row.id === detailId || row.school_id === detailId);
      if (!school) return <StatePanel state="empty" message="对象不存在或不可访问。"/>;
      const schoolId = school.school_id ?? school.id;
      return <>
        <PageHead eyebrow="学校投影" title="学校详情" description="只读学校绑定、生命周期和平台 school-scope 范围；不读取学校账号。"/>
        <Notice tone="warn">OMS 不管理学校账号或 TMS tenant.* 角色；这里只展示平台人员 school-scope 可见的学校投影。</Notice>
        <DetailGrid rows={[
          { label: "学校名称", value: school.school_name?.trim() || "未返回" },
          { label: "学校代码", value: school.school_code?.trim() || "—" },
          { label: "学校 ID", value: schoolId },
          { label: "外部绑定", value: statusLabel(school.external_binding?.status, model?.statusCatalog) },
          { label: "生命周期", value: statusLabel(school.lifecycle?.external_eligibility, model?.statusCatalog) },
          { label: "供给状态", value: statusLabel(school.lifecycle?.provisioning_status, model?.statusCatalog) },
          { label: "恢复状态", value: statusLabel(school.lifecycle?.recovery_state, model?.statusCatalog) },
        ]}/>
        <Section title="服务授权与额度摘要" subtitle="只读来自学校投影的服务授权、额度和用量聚合；不展示租户费用或学校账号。">
          <DetailGrid rows={[
            { label: "服务授权", value: statusCountSummary(school.service_entitlements, model?.statusCatalog) },
            { label: "额度", value: quotaGrantSummary(school.quota_grants, model?.statusCatalog) },
            { label: "用量", value: usageSummary(school.usage, model?.statusCatalog) },
          ]}/>
        </Section>
        <Section title="关联只读入口">
          <div className="inline-list">
            <Button onClick={() => navigate(`${OMS_BASE}/usage/school/${encodeRoutePart(schoolId)}`)}>查看该学校用量入口</Button>
            <Button onClick={() => navigate(`${OMS_BASE}/supply`)}>查看供给与额度底座</Button>
            <Button onClick={() => navigate(`${OMS_BASE}/school-permissions`)}>查看平台人员学校范围</Button>
          </div>
        </Section>
      </>;
    }
    if (detailRoot === "services") {
      const service = serviceRows.find(item => item.id === detailId);
      const legacyModel = modelRows.find(item => item.id === detailId);
      if (!service && legacyModel) {
        return <>
          <PageHead eyebrow="模型详情" title={legacyModel.model_id ?? legacyModel.model ?? legacyModel.id} description="服务端 DTO 的模型草稿投影；凭据与 Secret 不在前端回显。"/>
          <DetailGrid rows={[
            { label: "模型", value: legacyModel.model_id ?? legacyModel.model ?? legacyModel.id },
            { label: "Profile", value: legacyModel.profile_id ?? "—" },
            { label: "供应商", value: legacyModel.provider ?? "—" },
            { label: "模型草稿版本", value: `v${model?.modelDraftVersion ?? 0}` },
            { label: "模型草稿状态", value: modelDraftStatusLabel },
            { label: "状态", value: statusLabel(legacyModel.status, model?.statusCatalog) },
            { label: "来源", value: legacyModel.source ?? "正式 DTO" },
          ]}/>
        </>;
      }
      if (!service) return <StatePanel state="empty" message="对象不存在或不可访问。"/>;
      const scopedModels = modelRows.filter(row => serviceIdFromModel(row) === service.id);
      const scopedProfiles = profileRowsForService(service.id);
      const selectedModel = serviceView === "models" && serviceItemId ? scopedModels.find(row => row.id === serviceItemId) : undefined;
      const selectedProfile = serviceView === "provider" && serviceItemId ? scopedProfiles.find(row => row.id === serviceItemId) : undefined;
      if (selectedModel) {
        return <>
          <PageHead eyebrow="模型详情" title={selectedModel.model_id ?? selectedModel.model ?? selectedModel.id} breadcrumbs={[{ label: "模型与服务", onClick: () => navigate(`${OMS_BASE}/services`) }, { label: service.name, onClick: () => openServiceView(service.id, "models") }, { label: selectedModel.model_id ?? selectedModel.model ?? selectedModel.id }]} description="模型归属于本服务 Provider Profile；Secret 不在模型详情回显。"/>
          <DetailGrid rows={[
            { label: "名称", value: selectedModel.model_id ?? selectedModel.model ?? selectedModel.id },
            { label: "模型标识", value: selectedModel.model_id ?? selectedModel.model ?? "—" },
            { label: "所属 Profile", value: selectedModel.profile_id ?? "—" },
            { label: "服务", value: service.name },
            { label: "供应商", value: selectedModel.provider ?? "—" },
            { label: "状态", value: statusLabel(selectedModel.status, model?.statusCatalog) },
            { label: "来源", value: selectedModel.source ?? "正式 DTO" },
          ]}/>
        </>;
      }
      if (selectedProfile) {
        return <>
          <PageHead eyebrow="Provider Profile" title={selectedProfile.profile_id} breadcrumbs={[{ label: "模型与服务", onClick: () => navigate(`${OMS_BASE}/services`) }, { label: service.name, onClick: () => openServiceView(service.id, "provider") }, { label: selectedProfile.profile_id }]} description="Profile 与供应商连接分层展示；凭据明文不在详情回显。"/>
          <DetailGrid rows={[
            { label: "名称", value: selectedProfile.profile_id },
            { label: "供应商", value: selectedProfile.provider ?? "—" },
            { label: "服务", value: service.name },
            { label: "状态", value: statusLabel(selectedProfile.status, model?.statusCatalog) },
            { label: "关联模型数", value: String(selectedProfile.model_count) },
            { label: "来源", value: selectedProfile.source ?? "正式 DTO" },
          ]}/>
          <Notice tone="info">凭据状态请到供应商连接核对；Secret 明文不可见。</Notice>
        </>;
      }
      if (serviceView === "config") {
        return <>
          <PageHead eyebrow="服务详情" title={service.name} description={service.description} breadcrumbs={[{ label: "模型与服务", onClick: () => navigate(`${OMS_BASE}/services`) }, { label: service.name }]}/>
          <Section title="配置概况" subtitle="正式 OMS 只展示后端 DTO 与受控写入口；配置真实生效仍以服务端版本和测试结果为准。" action={canManageProviders ? <div className="table-actions" aria-label="模型与服务配置操作">
            <button type="button" className="table-link" onClick={openModelDraftJsonForm}>保存模型草稿 JSON</button>
            <button type="button" className="table-link" onClick={() => openProviderSettingsJsonForm()}>导入 Provider 设置 JSON</button>
            <button type="button" className="table-link" onClick={() => modelCommand("/api/v1/oms/models/test", "测试模型草稿")}>测试模型草稿</button>
            <button type="button" className="table-link" onClick={() => modelCommand("/api/v1/oms/models/publish", "发布模型草稿")}>发布模型草稿</button>
            <button type="button" className="table-link" onClick={() => modelCommand("/api/v1/oms/models/rollback", "回滚模型草稿")}>回滚模型草稿</button>
            <button type="button" className="table-link" onClick={() => providerCommand("/api/v1/oms/provider-settings/test", "测试 Provider 草稿")}>测试 Provider 草稿</button>
            <button type="button" className="table-link" onClick={() => providerCommand("/api/v1/oms/provider-settings/publish", "发布 Provider 草稿")}>发布 Provider 草稿</button>
            <button type="button" className="table-link" onClick={() => providerCommand("/api/v1/oms/provider-settings/rollback", "回滚 Provider 草稿")}>回滚 Provider 草稿</button>
          </div> : undefined}>
            <DetailGrid rows={[
              { label: "服务", value: service.name },
              { label: "计量单位", value: service.unit },
              { label: "模型草稿", value: `v${model?.modelDraftVersion ?? 0} · ${modelDraftStatusLabel}` },
              { label: "Provider 设置", value: `v${model?.providerSettingsVersion ?? 0} · ${providerSettingsStatusLabel}` },
              { label: "配置来源", value: service.source ?? "正式 DTO" },
              { label: "真实生效", value: "以服务端发布版本为准" },
            ]}/>
          </Section>
          <Notice tone="info">Secret、API Key 与供应商成本不会在服务配置详情回显。</Notice>
        </>;
      }
      if (serviceView === "provider") {
        return <>
          <PageHead eyebrow="服务详情" title={service.name} description={service.description} breadcrumbs={[{ label: "模型与服务", onClick: () => navigate(`${OMS_BASE}/services`) }, { label: service.name }]}/>
          <Section title="Provider Profile" subtitle="草稿不代表真实配置生效">
            <DataTable rows={scopedProfiles} searchLabel="搜索 Profile" emptyText="正式 DTO 未返回该服务 Provider Profile。" columns={[
              { key: "profile", label: "Profile", render: row => <><span className="cell-title">{row.profile_id}</span><span className="cell-sub">{row.provider ?? "未返回供应商"}</span></> },
              { key: "status", label: "状态", render: row => statusLabel(row.status, model?.statusCatalog) },
              { key: "models", label: "关联模型数", render: row => String(row.model_count) },
            ]} rowActions={row => [{
              label: "Profile 详情",
              onClick: () => openServiceView(service.id, "provider", row.id),
            }]}/>
            {CONNECTABLE_SERVICE_IDS.has(service.id) && <Button onClick={() => openServiceView(service.id, "connections")}>适用连接</Button>}
          </Section>
        </>;
      }
      if (serviceView === "models") {
        return <>
          <PageHead eyebrow="服务详情" title={service.name} description={service.description} breadcrumbs={[{ label: "模型与服务", onClick: () => navigate(`${OMS_BASE}/services`) }, { label: service.name }]}/>
          <Section title="模型清单" subtitle="模型归属于本服务 Provider Profile">
            <DataTable rows={scopedModels} searchLabel="搜索模型" emptyText="正式 DTO 未返回该服务模型清单。" columns={[
              { key: "model", label: "模型", render: row => <><span className="cell-title">{row.model_id ?? row.model ?? row.id}</span><span className="cell-sub">{row.provider ?? "未返回供应商"}</span></> },
              { key: "profile", label: "所属 Profile", render: row => row.profile_id ?? "—" },
              { key: "status", label: "状态", render: row => statusLabel(row.status, model?.statusCatalog) },
              { key: "source", label: "来源", render: row => row.source ?? "正式 DTO" },
            ]} rowActions={row => [{
              label: "模型详情",
              onClick: () => openServiceView(service.id, "models", row.id),
            }]}/>
          </Section>
        </>;
      }
      if (serviceView === "relations") {
        return <>
          <PageHead eyebrow="服务详情" title={service.name} description={service.description} breadcrumbs={[{ label: "模型与服务", onClick: () => navigate(`${OMS_BASE}/services`) }, { label: service.name }]}/>
          <Section title="关联记录" subtitle="选择关系类型后查看当前服务的具体记录与操作">
            <div className="inline-list">
              <Button onClick={() => openServiceView(service.id, "supply")}>关联供给</Button>
              <Button onClick={() => openServiceView(service.id, "schools")}>授权学校</Button>
              <Button onClick={() => openServiceView(service.id, "grants")}>关联额度</Button>
              <Button onClick={() => openServiceView(service.id, "usage")}>用量记录</Button>
              {CONNECTABLE_SERVICE_IDS.has(service.id) && <Button onClick={() => openServiceView(service.id, "connections")}>适用连接</Button>}
            </div>
          </Section>
        </>;
      }
      if (serviceView === "supply") {
        return <Section title="关联供给"><DataTable rows={supplyLotRows.filter(row => row.service_id === service.id)} searchLabel="搜索关联供给" emptyText="正式 DTO 未返回该服务供给批次。" columns={[
          { key: "provider", label: "Provider", render: row => row.provider_id ?? "—" },
          { key: "pool", label: "Pool", render: row => row.pool_id ?? "—" },
          { key: "status", label: "状态", render: row => statusLabel(row.status, model?.statusCatalog) },
        ]}/></Section>;
      }
      if (serviceView === "schools") {
        return <Section title="授权学校"><DataTable rows={schoolRows.filter(row => row.service_entitlements?.some(item => statusCode(item.status) || item.count))} searchLabel="搜索授权学校" emptyText="正式 DTO 未返回该服务授权学校。" columns={[
          { key: "school_name", label: "学校名称", render: row => schoolListName(row) },
          { key: "school_code", label: "学校代码", render: row => schoolListCode(row) },
          { key: "binding", label: "绑定", render: row => statusLabel(row.external_binding?.status, model?.statusCatalog) },
          { key: "lifecycle", label: "生命周期", render: row => statusLabel(row.lifecycle?.external_eligibility, model?.statusCatalog) },
        ]}/></Section>;
      }
      if (serviceView === "grants") {
        return <Section title="关联额度"><DataTable rows={quotaGrantRows.filter(row => row.service_id === service.id)} searchLabel="搜索关联额度" emptyText="正式 DTO 未返回该服务额度记录。" columns={[
          { key: "grant", label: "额度", render: row => row.grant_id ?? row.id },
          { key: "quantity", label: "数量", render: row => `${row.quantity ?? "0"} ${row.unit_code ?? service.unit}` },
          { key: "status", label: "状态", render: row => statusLabel(row.status, model?.statusCatalog) },
        ]}/></Section>;
      }
      if (serviceView === "usage") {
        return <Section title="用量记录"><DataTable rows={usageRows.filter(row => row.service_id === service.id)} searchLabel="搜索服务调用" emptyText="正式 DTO 未返回该服务用量记录。" columns={[
          { key: "attempt", label: "Attempt", render: row => row.attempt_id ?? row.id },
          { key: "operation", label: "Operation", render: row => row.operation_id ?? "—" },
          { key: "status", label: "状态", render: row => statusLabel(row.status, model?.statusCatalog) },
        ]}/></Section>;
      }
      if (serviceView === "connections") {
        const scopedConnectionRows = providerRows.filter(row => connectionServiceIds(row).includes(service.id));
        return <Section title="适用连接"><DataTable rows={scopedConnectionRows} searchLabel="搜索适用连接" emptyText="正式 DTO 未返回该服务适用连接。" columns={[
          { key: "name", label: "连接", render: row => row.provider ?? row.id },
          { key: "scope", label: "适用服务", render: row => connectionServiceScope(row) },
          { key: "status", label: "状态", render: () => providerSettingsStatusLabel },
        ]} rowActions={row => [{
          label: "连接资料",
          onClick: () => openDetail("connections", row.id),
        }]}/></Section>;
      }
      if (serviceView === "release") {
        return <>
          <PageHead eyebrow="服务详情" title={service.name} description={service.description} breadcrumbs={[{ label: "模型与服务", onClick: () => navigate(`${OMS_BASE}/services`) }, { label: service.name }]}/>
          <Section title="发布与生效记录" subtitle="仅展示服务端版本与状态；未返回历史记录时不合成发布记录。">
            <DetailGrid rows={[
              { label: "模型草稿版本", value: `v${model?.modelDraftVersion ?? 0}` },
              { label: "模型草稿状态", value: modelDraftStatusLabel },
              { label: "Provider 设置版本", value: `v${model?.providerSettingsVersion ?? 0}` },
              { label: "Provider 设置状态", value: providerSettingsStatusLabel },
            ]}/>
          </Section>
        </>;
      }
      return <>
        <PageHead eyebrow="服务详情" title={service.name} description={service.description} breadcrumbs={[{ label: "模型与服务", onClick: () => navigate(`${OMS_BASE}/services`) }, { label: service.name }]}/>
        <DetailGrid rows={[
          { label: "服务", value: service.name },
          { label: "类别", value: service.category },
          { label: "状态", value: statusLabel(service.rawStatus, model?.statusCatalog) || service.status },
          { label: "计量单位", value: service.unit },
          { label: "来源", value: service.source ?? "正式 DTO" },
        ]}/>
        <Notice>未返回的服务配置不以原型合成数据补齐。</Notice>
      </>;
    }
    if (detailRoot === "connections") {
      const row = providerRows.find(item => item.id === detailId);
      return row ? <>
        <PageHead eyebrow="连接详情" title={row.provider ?? row.id} description="连接元数据与凭据维护分开操作；凭据明文不在详情回显。" breadcrumbs={[{ label: "供应商连接", onClick: () => navigate(`${OMS_BASE}/connections`) }, { label: row.provider ?? row.id }]}/>
        <DetailGrid rows={[
          { label: "供应商", value: row.provider ?? "—" },
          { label: "适用服务", value: connectionServiceScope(row) },
          { label: "状态", value: providerSettingsStatusLabel },
          { label: "凭据状态", value: connectionCredentialStatus(row) },
          { label: "Base URL", value: row.base_url ?? "后端默认或未返回" },
          { label: "备注", value: `Provider 设置 v${model?.providerSettingsVersion ?? 0}` },
          { label: "凭据引用", value: redactedCredentialLabel() },
        ]}/>
        <Notice tone="info">Secret 明文不可见；凭据只允许后端保存并以脱敏占位展示。</Notice>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (["agents", "tools", "knowledge", "runtime"].includes(detailRoot)) {
      const row = resourceRows.find(item => item.id === detailId);
      const safeRows = row ? safeFieldRows(row) : [];
      return row ? <>
        <PageHead eyebrow="资源目录" title="资源详情" description="平台资源状态来自安全 descriptor；策略和运行参数由后续正式 DTO 承接。"/>
        <DetailGrid rows={[
          { label: "资源", value: row.display_name ?? row.id },
          { label: "类别", value: row.category ?? row.kind ?? "unknown" },
          { label: "状态", value: statusLabel(row.status, model?.statusCatalog) },
          { label: "托管", value: row.managed ? "是" : "否" },
        ]}/>
        {statusDescription(row.status, model?.statusCatalog) && <Notice tone={statusNoticeTone(row.status, model?.statusCatalog)}>{statusDescription(row.status, model?.statusCatalog)}</Notice>}
        {safeRows.length > 0 && <Section title="安全字段">
          <DetailGrid rows={safeRows}/>
        </Section>}
        <Notice>未返回的运行参数不以原型合成数据补齐。</Notice>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "supply") {
      const definition = supplyDefinitionRows.find(item => item.id === detailId);
      const lot = supplyLotRows.find(item => item.id === detailId);
      return definition || lot ? <>
        <PageHead eyebrow="服务供给" title="供给详情" description="服务定义和供给批次只读；TMS 不能修改额度，OMS 写入另走受控 API。"/>
        <DetailGrid rows={[
          { label: "服务", value: definition?.service_id ?? lot?.service_id ?? detailId },
          { label: "单位", value: definition?.unit_code ?? lot?.unit_code ?? "unit" },
          { label: "资源类别", value: definition?.resource_category ?? lot?.provider_id ?? "—" },
          { label: "状态", value: definition ? (definition.enabled ? "enabled" : "disabled") : statusLabel(lot?.status, model?.statusCatalog) },
          { label: "剩余额度", value: lot?.committed_unspent ?? "—" },
        ]}/>
        {!definition && statusDescription(lot?.status, model?.statusCatalog) && <Notice tone={statusNoticeTone(lot?.status, model?.statusCatalog)}>{statusDescription(lot?.status, model?.statusCatalog)}</Notice>}
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "usage") {
      const attempt = usageRows.find(item => item.id === detailId) ?? jobRows.find(item => item.id === detailId);
      if (!attempt) return <StatePanel state="empty" message="对象不存在或不可访问。"/>;
      const attemptStatusDescription = statusDescription(attempt.status, model?.statusCatalog);
      return <>
        <PageHead eyebrow="用量与运行" title="调用详情" description="逐 attempt 只读投影；未知结果不得在前端按零处理。"/>
        <DetailGrid rows={[
          { label: "Attempt", value: attempt.attempt_id ?? attempt.id },
          { label: "Operation", value: attempt.operation_id ?? "—" },
          { label: "服务", value: attempt.service_id ?? "unknown" },
          { label: "状态", value: statusLabel(attempt.status, model?.statusCatalog) },
          { label: "单位", value: `${attempt.settled_units ?? "0"}/${attempt.reserved_units ?? "0"} ${attempt.unit_code ?? "unit"}` },
        ]}/>
        {attemptStatusDescription && <Notice tone={statusNoticeTone(attempt.status, model?.statusCatalog)}>{attemptStatusDescription}</Notice>}
      </>;
    }
    if (detailRoot === "platform-people") {
      const principal = authzPrincipalRows.find(item => item.id === detailId || item.principal_id === detailId);
      if (!principal) return <StatePanel state="empty" message="平台主体不存在或不可访问。"/>;
      const principalId = principal.principal_id ?? principal.id;
      const relatedAssignments = authzAssignmentRows.filter(item => item.principal_id === principalId || item.principal_id === principal.id);
      return <>
        <PageHead eyebrow="授权治理" title="平台主体详情" description="候选只来自可信 OMS 登录登记和本地权限事实；不读取学校账号目录。"/>
        <DetailGrid rows={[
          { label: "Principal ID", value: principalId ?? "—" },
          { label: "外部主体", value: principal.subject ?? "已登记平台主体" },
          { label: "状态", value: principal.status ?? "unknown" },
          { label: "Policy version", value: String(principal.policy_version ?? 0) },
          { label: "候选来源", value: "可信 OMS 登录登记 / DeepTutor Enterprise 本地事实" },
        ]}/>
        <Section title="当前授权范围">
          <DataTable rows={relatedAssignments.map((item, index) => ({ ...item, id: item.id ?? item.assignment_id ?? `principal-assignment-${index}` }))} searchLabel="搜索主体授权" emptyText="该主体暂无当前可见授权范围" columns={[
            { key: "role", label: "角色", render: row => row.role_key ?? row.id },
            { key: "scope", label: "范围", render: row => row.school_id ? `学校 ${row.school_id}` : row.scope_kind ?? "platform" },
            { key: "status", label: "状态", render: row => `${row.status ?? "unknown"} · v${row.version ?? 0}` },
          ]}/>
        </Section>
      </>;
    }
    if (detailRoot === "platform-roles") {
      const role = authzRoleRows.find(item => item.id === detailId);
      return role ? <>
        <PageHead eyebrow="授权治理" title="角色模板详情" description="角色模板版本化登记；新版本不会静默扩展既有 assignment。"/>
        <DetailGrid rows={[
          { label: "角色", value: role.role_key ?? role.id },
          { label: "版本", value: `v${role.version ?? 0}` },
          { label: "范围", value: role.scope_kind ?? "unknown" },
          { label: "动作", value: role.actions?.join("、") || "未返回动作" },
        ]}/>
      </> : <StatePanel state="empty" message="角色模板不存在或不可访问。"/>;
    }
    if (detailRoot === "school-permissions") {
      const assignment = authzAssignmentRows.find(item => item.id === detailId || item.assignment_id === detailId);
      const assignmentId = assignment?.assignment_id ?? assignment?.id ?? "";
      const principal = authzPrincipalRows.find(item => item.principal_id === assignment?.principal_id || item.id === assignment?.principal_id);
      return assignment ? <>
        <PageHead eyebrow="授权治理" title="授权范围详情" description="范围来自后端安全 DTO；写入时仍由服务端复核 principal、assignment 与 policy version。"/>
        <DetailGrid rows={[
          { label: "Assignment ID", value: assignmentId },
          { label: "主体", value: principal?.subject ?? assignment.principal_id ?? "—" },
          { label: "角色", value: `${assignment.role_key ?? "unknown"} v${assignment.role_version ?? 0}` },
          { label: "范围", value: assignment.school_id ? `学校 ${assignment.school_id}` : assignment.scope_kind ?? "platform" },
          { label: "状态", value: assignment.status ?? "unknown" },
          { label: "Assignment version", value: String(assignment.version ?? 0) },
        ]}/>
        {assignment.status === "active" && assignmentId && <Button onClick={() => runCommand("撤销 OMS 授权", `/api/v1/oms/assignments/${encodeURIComponent(assignmentId)}/revoke`, {
          target_school_id: assignment.school_id || null,
          expected_assignment_version: assignment.version ?? 1,
          expected_target_policy_version: principal?.policy_version ?? 1,
          command_id: commandId(),
          reason,
        })}>撤销此 OMS 授权</Button>}
      </> : <StatePanel state="empty" message="授权范围不存在或不可访问。"/>;
    }
    if (detailRoot === "audit" || detailRoot === "authz-audit") {
      const approval = approvalRows.find(item => item.id === detailId || item.approval_id === detailId);
      if (detailRoot === "authz-audit" && approval) {
        const approvalId = approval.approval_id ?? approval.id ?? "";
        const target = approval.target_role_key ? `${approval.target_role_key} v${approval.target_role_version ?? 0}` : (approval.target_action_keys?.join("、") || approval.target_principal_id || "—");
        return <>
          <PageHead eyebrow="授权治理" title="授权审批详情" description="审批详情来自本地授权事实；批准/apply 写入仍调用正式 OMS API。"/>
          <DetailGrid rows={[
            { label: "审批 ID", value: approvalId },
            { label: "操作", value: approval.operation ?? "—" },
            { label: "目标主体", value: approval.target_principal_id ?? "—" },
            { label: "目标", value: target },
            { label: "状态", value: approval.status ?? "unknown" },
            { label: "目标 policy version", value: String(approval.expected_target_policy_version ?? 0) },
          ]}/>
          <div className="inline-list">
            {approval.status === "pending" && approvalId && <Button onClick={() => runCommand("批准授权审批", `/api/v1/oms/approvals/${encodeURIComponent(approvalId)}/review`, {
              decision: "approved",
              expected_target_policy_version: approval.expected_target_policy_version ?? 1,
              reason,
            })}>批准此审批</Button>}
            {approval.status === "approved" && approvalId && <Button onClick={() => runCommand("应用授权审批", `/api/v1/oms/approvals/${encodeURIComponent(approvalId)}/apply`, {
              expected_target_policy_version: approval.expected_target_policy_version ?? 1,
              command_id: commandId(),
              reason,
            })}>应用此审批</Button>}
          </div>
        </>;
      }
      const event = auditRows.find(item => item.id === detailId || item.request_id === detailId);
      return event ? <>
        <PageHead eyebrow="审计详情" title="授权与操作审计" description="审计回读只显示脱敏动作、结果与 request ID。"/>
        <DetailGrid rows={[
          { label: "事件", value: event.id ?? event.request_id ?? detailId },
          { label: "动作", value: event.action ?? "—" },
          { label: "结果", value: statusLabel(event.result, model?.statusCatalog) },
          { label: "请求", value: event.request_id ?? "—" },
          { label: "原因", value: event.reason ?? "—" },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "skills") {
      const row = skillRows.find(item => item.id === detailId || item.name === detailId);
      return row ? <>
        <PageHead eyebrow="Skill" title="Skill 详情" description="Skill 正式维护只显示包状态、发布版本和脱敏校验信息。"/>
        <DetailGrid rows={[
          { label: "Skill", value: row.name ?? row.id },
          { label: "状态", value: row.status ?? "unknown" },
          { label: "最新版本", value: String(row.latest_version ?? row.latest_revision ?? 0) },
          { label: "已发布版本", value: String(row.published_version ?? row.published_revision ?? 0) },
          { label: "校验摘要", value: row.sha256 ? `${row.sha256.slice(0, 12)}…` : "未返回" },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    return null;
  })();

  return shell(<>
    {root !== "services" && root !== "connections" && <PageHead title="平台智能体运营后台" description="正式入口使用已验签 OMS 会话与 DeepTutor 本地 ops.* 授权；不接学校账号或 TMS 首管开通。"/>}
    {root !== "services" && root !== "connections" && <Notice tone="info">当前页面只渲染后端安全 DTO；Secret、对象存储 key、成本明细和学校私有正文不会在这里出现。</Notice>}
    {commandMessage && <Notice tone={commandMessage.includes("被拒绝") ? "bad" : "info"}>{commandMessage}</Notice>}
    {root !== "services" && root !== "connections" && <MetricStrip items={[
      { label: "可见学校", value: String(model?.summary.authorized_school_count ?? schoolRows.length), note: "显式 school-scope" },
      { label: "资源", value: String(model?.summary.resource_count ?? resourceRows.length), note: "安全状态投影" },
      { label: "待审批", value: String(approvalRows.filter(item => item.status === "pending" || item.status === "approved").length), note: "本地授权事实" },
      { label: "Skill", value: String(skillRows.length), note: "首个 Agent 接入" },
    ]}/>}
    {root === "home" && <>
      <Section title="当前平台身份"><DetailGrid rows={[
        { label: "主体", value: model?.me.display_name ?? model?.me.subject ?? model?.me.principal_id ?? "已认证平台主体" },
        { label: "状态", value: <StatusBadge tone="good">{model?.me.status ?? "active"}</StatusBadge> },
        { label: "动作", value: actions.length ? actions.join("、") : "无本地授权" },
      ]}/></Section>
      <Section title="OMS 总览" subtitle="只聚合当前平台主体本地 ops.* 范围内可见的学校与资源。">
        <DetailGrid rows={[
          { label: "可见学校", value: String(model?.summary.authorized_school_count ?? 0) },
          { label: "资源数量", value: String(model?.summary.resource_count ?? resourceRows.length) },
          { label: "治理提示", value: model?.summary.notices?.map(item => item.label ?? item.code).filter(Boolean).join("、") || "—" },
        ]}/>
      </Section>
    </>}
    {(root === "home" || root === "agents" || root === "tools" || root === "knowledge" || root === "runtime") && <Section title="平台资源状态" subtitle="安全状态投影只展示 descriptor 与脱敏字段。">
      <DataTable rows={visibleResourceRows} searchLabel="搜索资源" columns={[
        { key: "name", label: "资源", render: row => row.display_name ?? row.id },
        { key: "category", label: "类别", render: row => row.category ?? row.kind ?? "unknown" },
        { key: "status", label: "状态", render: row => statusLabel(row.status, model?.statusCatalog) },
      ]} emptyText={resourceEmptyText(root)} onOpen={row => openDetail(root === "home" ? "runtime" : root, row.id)} openLabel={row => `查看 ${row.display_name ?? row.id} 详情`}/>
    </Section>}
    {(root === "home" || root === "tenants") && <Section title="学校范围" subtitle="仅列出当前 OMS 主体已获本产品 school-scope 授权的学校。">
      <DataTable rows={schoolRows} searchLabel="搜索学校" columns={[
        { key: "school_name", label: "学校名称", render: row => <span className="cell-title">{schoolListName(row)}</span> },
        { key: "school_code", label: "学校代码", render: row => schoolListCode(row) },
        { key: "binding", label: "绑定", render: row => statusLabel(row.external_binding?.status, model?.statusCatalog) },
        { key: "lifecycle", label: "生命周期", render: row => statusLabel(row.lifecycle?.external_eligibility, model?.statusCatalog) },
      ]} onOpen={row => openDetail("tenants", row.school_id ?? row.id)} openLabel={row => `查看 ${schoolDisplayName(row)} 详情`}/>
    </Section>}
    {canManagePermissions && (root === "home" || root === "platform-people" || root === "platform-roles" || root === "school-permissions" || root === "authz-audit") && <Section title="平台授权治理" subtitle="平台人员、角色、学校操作范围和审批均接入正式 OMS 本地授权 API；候选只来自已登记平台主体。">
      <div className="section-grid">
        <DataTable rows={authzPrincipalRows} searchLabel="搜索平台人员" columns={[
          { key: "subject", label: "平台主体", render: row => row.subject ?? row.principal_id ?? row.id },
          { key: "status", label: "状态", render: row => row.status ?? "unknown" },
          { key: "version", label: "Policy", render: row => String(row.policy_version ?? 0) },
        ]} rowActions={row => {
          const principalId = row.principal_id ?? row.id ?? "";
          const targetPolicyVersion = row.policy_version ?? 1;
          return [
            {
              label: "查看平台主体详情",
              onClick: () => openDetail("platform-people", principalId),
            },
            ...(row.status === "pending" && configRole?.role_key && configRole.version ? [{
              label: "提交平台授权审批",
              onClick: () => runCommand("提交平台授权审批", "/api/v1/oms/approvals", {
                operation: "platform_grant",
                target_principal_id: principalId,
                expected_target_policy_version: targetPolicyVersion,
                expires_at: "9998-12-31T00:00:00Z",
                idempotency_key: commandId(),
                reason,
                external_qualification_ref: "oms-formal-ui",
                external_qualification_version: "ui-v1",
                target_role_key: configRole.role_key,
                target_role_version: configRole.version,
                confirmed_role_version: configRole.version,
                target_expires_at: farFutureIso(),
              }),
            }] : []),
            ...(row.status === "active" && schoolAuditRole?.role_key && schoolAuditRole.version && model?.inspectedSchoolId ? [{
              label: "授予学校只读范围",
              onClick: () => runCommand("授予学校只读范围", `/api/v1/oms/principals/${encodeURIComponent(principalId)}/roles`, {
                role_key: schoolAuditRole.role_key,
                role_version: schoolAuditRole.version,
                target_school_id: model.inspectedSchoolId,
                expected_target_policy_version: targetPolicyVersion,
                expires_at: farFutureIso(),
                command_id: commandId(),
                reason,
              }),
            }] : []),
            ...(row.status === "active" ? [{
              label: "停用平台主体",
              onClick: () => runCommand("停用平台主体", `/api/v1/oms/principals/${encodeURIComponent(principalId)}/disable`, {
                expected_target_policy_version: targetPolicyVersion,
                reason,
              }),
            }] : []),
          ];
        }}/>
        <DataTable rows={authzRoleRows} searchLabel="搜索角色" columns={[
          { key: "role", label: "角色", render: row => row.role_key ?? row.id },
          { key: "scope", label: "范围", render: row => `${row.scope_kind ?? "unknown"} · v${row.version ?? 0}` },
          { key: "actions", label: "动作", render: row => row.actions?.join("、") || "—" },
        ]} rowActions={row => [{
          label: "查看角色模板详情",
          onClick: () => openDetail("platform-roles", row.id),
        }]}/>
      </div>
      <div className="section-grid">
        <DataTable rows={authzAssignmentRows} searchLabel="搜索授权范围" columns={[
          { key: "role", label: "角色", render: row => row.role_key ?? row.id },
          { key: "scope", label: "范围", render: row => row.school_id ? `学校 ${row.school_id}` : row.scope_kind ?? "platform" },
          { key: "status", label: "状态", render: row => `${row.status ?? "unknown"} · v${row.version ?? 0}` },
        ]} rowActions={row => {
          const assignmentId = row.assignment_id ?? row.id ?? "";
          const principal = authzPrincipalRows.find(item => item.principal_id === row.principal_id || item.id === row.principal_id);
          return [
            {
              label: "查看授权范围详情",
              onClick: () => openDetail("school-permissions", assignmentId),
            },
            ...(row.status === "active" ? [{
              label: "撤销 OMS 授权",
              onClick: () => runCommand("撤销 OMS 授权", `/api/v1/oms/assignments/${encodeURIComponent(assignmentId)}/revoke`, {
                target_school_id: row.school_id || null,
                expected_assignment_version: row.version ?? 1,
                expected_target_policy_version: principal?.policy_version ?? 1,
                command_id: commandId(),
                reason,
              }),
            }] : []),
          ];
        }}/>
        <DataTable rows={approvalRows} searchLabel="搜索审批" columns={[
          { key: "operation", label: "审批", render: row => row.operation ?? row.id },
          { key: "target", label: "目标", render: row => row.target_role_key ? `${row.target_role_key} v${row.target_role_version ?? 0}` : (row.target_action_keys?.join("、") || row.target_principal_id || "—") },
          { key: "status", label: "状态", render: row => row.status ?? "unknown" },
        ]} rowActions={row => {
          const approvalId = row.approval_id ?? row.id ?? "";
          const targetPolicyVersion = row.expected_target_policy_version ?? 1;
          return [
            {
              label: "查看审批详情",
              onClick: () => openDetail("authz-audit", approvalId),
            },
            ...(row.status === "pending" ? [{
              label: "批准授权审批",
              onClick: () => runCommand("批准授权审批", `/api/v1/oms/approvals/${encodeURIComponent(approvalId)}/review`, {
                decision: "approved",
                expected_target_policy_version: targetPolicyVersion,
                reason,
              }),
            }] : []),
            ...(row.status === "approved" ? [{
              label: "应用授权审批",
              onClick: () => runCommand("应用授权审批", `/api/v1/oms/approvals/${encodeURIComponent(approvalId)}/apply`, {
                expected_target_policy_version: targetPolicyVersion,
                command_id: commandId(),
                reason,
              }),
            }] : []),
          ];
        }}/>
      </div>
    </Section>}
    {root === "services" && <>
      <PageHead eyebrow="资源目录" title="模型与服务" description="按基座服务语义管理平台目录；配置与实际生效分离。" actions={canManageProviders ? <Button variant="primary" onClick={openModelDraftJsonForm}>保存模型草稿 JSON</Button> : undefined}/>
      <Notice tone="info">模型草稿 v{model?.modelDraftVersion ?? 0} · {modelDraftStatusLabel}；Provider 设置 v{model?.providerSettingsVersion ?? 0} · {providerSettingsStatusLabel}。</Notice>
      <Tabs tabs={["全部服务", "文档识别与解析"]} active={catalogTab} onChange={setCatalogTab}/>
      {catalogTab === "全部服务"
        ? <ServiceList services={serviceRows} showHeading={false} state="ready" rowActions={serviceActions}/>
        : <OcrServiceList services={serviceRows.filter(row => DOCUMENT_SERVICE_IDS.has(row.id))} showHeading={false} state="ready" rowActions={serviceActions}/>}
    </>}
    {root === "connections" && <>
      <PageHead eyebrow="供应商连接" title="供应商连接" description="连接与服务配置分层维护；凭据由高权限角色处理。" actions={canManageProviders ? <Button variant="primary" onClick={() => openProviderSettingsJsonForm()}>导入 Provider 设置 JSON</Button> : undefined}/>
      <Notice tone="info">供应商连接配置版本 v{model?.providerSettingsVersion ?? 0} · {providerSettingsStatusLabel}；Secret 明文不可见。</Notice>
      <Section>
        <DataTable rows={providerRows} searchLabel="搜索连接" searchText={row => [row.id, row.provider, row.base_url, connectionServiceScope(row), providerSettingsStatusLabel, connectionCredentialStatus(row)].filter(Boolean).join(" ")} emptyText="没有符合条件的记录" columns={[
          { key: "name", label: "连接", render: row => <><span className="cell-title">{row.provider ?? row.id}</span><span className="cell-sub">{row.base_url ?? "供应商默认端点"}</span></> },
          { key: "scope", label: "适用服务", render: row => connectionServiceScope(row) },
          { key: "credential", label: "凭据状态", render: row => <><span>{connectionCredentialStatus(row)}</span><span className="cell-sub">{row.api_key ? redactedCredentialLabel() : "无凭据引用"}</span></> },
          { key: "status", label: "状态", render: () => providerSettingsStatusLabel },
        ]} rowActions={row => [
          {
            label: "连接资料",
            onClick: () => openDetail("connections", row.id),
          },
          ...(canManageProviders ? [{
            label: row.api_key ? "轮换凭据" : "配置凭据",
            onClick: () => openProviderSettingsJsonForm(row),
          }] : []),
        ]}/>
      </Section>
      {canManageProviders && <Notice tone="warn">凭据写入使用正式 Provider 设置草稿接口；请提交完整目标 JSON，Secret 只能填写后端可解析的 env: 引用，明文不会在列表或详情回显。</Notice>}
    </>}
    {root === "home" && <Section title="模型与 Provider" subtitle="草稿、测试、发布和回滚均调用正式 OMS 写 API；Secret 仅允许后端脱敏值。" action={canManageProviders ? <div className="table-actions" aria-label="模型与 Provider 操作">
      <button type="button" className="table-link" onClick={openModelDraftJsonForm}>保存模型草稿 JSON</button>
      <button type="button" className="table-link" onClick={() => openProviderSettingsJsonForm()}>导入 Provider 设置 JSON</button>
      <button type="button" className="table-link" onClick={() => modelCommand("/api/v1/oms/models/test", "测试模型草稿")}>测试模型草稿</button>
      <button type="button" className="table-link" onClick={() => modelCommand("/api/v1/oms/models/publish", "发布模型草稿")}>发布模型草稿</button>
      <button type="button" className="table-link" onClick={() => modelCommand("/api/v1/oms/models/rollback", "回滚模型草稿")}>回滚模型草稿</button>
      <button type="button" className="table-link" onClick={() => providerCommand("/api/v1/oms/provider-settings/test", "测试 Provider 草稿")}>测试 Provider 草稿</button>
      <button type="button" className="table-link" onClick={() => providerCommand("/api/v1/oms/provider-settings/publish", "发布 Provider 草稿")}>发布 Provider 草稿</button>
      <button type="button" className="table-link" onClick={() => providerCommand("/api/v1/oms/provider-settings/rollback", "回滚 Provider 草稿")}>回滚 Provider 草稿</button>
    </div> : undefined}>
      <Notice tone="info">
        {`模型草稿 v${model?.modelDraftVersion ?? 0} · ${modelDraftStatusLabel}；Provider 设置 v${model?.providerSettingsVersion ?? 0} · ${providerSettingsStatusLabel}。`}
      </Notice>
      <div className="section-grid">
        <DataTable rows={modelRows} searchLabel="搜索模型" columns={[
          { key: "model", label: "模型", render: row => row.model_id ?? row.model ?? row.id },
          { key: "profile", label: "Profile", render: row => row.profile_id ?? "—" },
          { key: "provider", label: "供应商", render: row => row.provider ? `${row.provider} · ${statusLabel(row.status, model?.statusCatalog)}` : "—" },
          { key: "status", label: "状态", render: row => statusLabel(row.status, model?.statusCatalog) },
          { key: "source", label: "来源", render: row => row.source ?? "正式 DTO" },
        ]} onOpen={row => openModelDetail(row)} openLabel={row => `查看 ${row.model_id ?? row.model ?? row.id} 详情`}/>
        <DataTable rows={providerRows} searchLabel="搜索 Provider" columns={[
          { key: "id", label: "连接", render: row => row.id },
          { key: "provider", label: "供应商", render: row => row.provider ? `${row.provider} · ${providerSettingsStatusLabel}` : "—" },
          { key: "base_url", label: "Base URL", render: row => row.base_url ?? "后端默认或未返回" },
          { key: "status", label: "状态", render: () => providerSettingsStatusLabel },
          { key: "secret", label: "凭据", render: () => redactedCredentialLabel() },
        ]} searchText={row => [row.id, row.provider, row.base_url, providerSettingsStatusLabel].filter(Boolean).join(" ")} emptyText={`Provider 设置：${providerSettingsStatusLabel}`} onOpen={row => openDetail("connections", row.id)} openLabel={row => `查看 ${row.provider ?? row.id} 详情`}/>
      </div>
    </Section>}
    {(root === "home" || root === "supply") && <Section title="供给与额度底座" subtitle="服务定义、供给批次、学校服务授权和额度 grant 均来自正式安全 DTO；写入按 ops.entitlements/manage 与 ops.quotas.manage 显隐。">
      <div className="section-grid">
        <DataTable rows={supplyDefinitionRows} searchLabel="搜索服务定义" columns={[
          { key: "service", label: "服务", render: row => row.service_id ?? row.id },
          { key: "unit", label: "单位", render: row => row.unit_code ?? "unit" },
          { key: "enabled", label: "状态", render: row => row.enabled ? "enabled" : "disabled" },
        ]} rowActions={canManageEntitlements && model?.inspectedSchoolId ? row => {
          const serviceId = row.service_id ?? row.id;
          const entitlement = entitlementRows.find(item => item.service_id === serviceId);
          const expectedVersion = entitlement?.version ?? 0;
          return [
            {
              label: "查看服务定义详情",
              onClick: () => openDetail("supply", row.id),
            },
            {
              label: "授权当前学校服务",
              onClick: () => entitlementCommand(serviceId, "active", expectedVersion),
            },
            ...(entitlement?.status === "active" || statusCode(entitlement?.status) === "active" ? [{
              label: "撤销当前学校服务授权",
              onClick: () => entitlementCommand(serviceId, "revoked", expectedVersion),
            }] : []),
          ];
        } : undefined} onOpen={!canManageEntitlements ? row => openDetail("supply", row.id) : undefined} openLabel={row => `查看 ${row.service_id ?? row.id} 详情`}/>
        <DataTable rows={supplyLotRows} searchLabel="搜索供给批次" columns={[
          { key: "provider", label: "Provider", render: row => row.provider_id ?? "—" },
          { key: "pool", label: "Pool", render: row => row.pool_id ?? "—" },
          { key: "status", label: "状态", render: row => `${statusLabel(row.status, model?.statusCatalog)} · ${row.committed_unspent ?? "0"} ${row.unit_code ?? "unit"}` },
        ]} rowActions={canManageSupply ? row => {
          const isActive = row.status === "active" || statusCode(row.status) === "active";
          const lotId = row.lot_id ?? row.id;
          return [
            {
              label: "查看供给详情",
              onClick: () => openDetail("supply", row.id),
            },
            ...(isActive && lotId ? [{
              label: "撤销供给批次",
              onClick: () => supplyRevokeCommand(row),
            }] : []),
          ];
        } : undefined} onOpen={!canManageSupply ? row => openDetail("supply", row.id) : undefined} openLabel={row => `查看 ${row.service_id ?? row.id} 供给详情`}/>
      </div>
      {(entitlementRows.length > 0 || quotaGrantRows.length > 0) && <div className="section-grid">
        <DataTable rows={entitlementRows} searchLabel="搜索服务授权" columns={[
          { key: "service", label: "服务授权", render: row => row.service_id ?? row.id },
          { key: "status", label: "状态", render: row => `${statusLabel(row.status, model?.statusCatalog)} · v${row.version ?? 0}` },
          { key: "expires", label: "有效期", render: row => row.expires_at ?? "未返回" },
        ]} rowActions={canManageQuotas && model?.inspectedSchoolId ? row => {
          const hasSupplyLot = supplyLotRows.some(item => item.service_id === row.service_id && item.provider_id && item.pool_id);
          return hasSupplyLot && (row.status === "active" || statusCode(row.status) === "active") ? [{
            label: "赠送当前学校额度",
            onClick: () => quotaGrantCommand(row),
          }] : [];
        } : undefined}/>
        <DataTable rows={quotaGrantRows} searchLabel="搜索额度 grant" columns={[
          { key: "service", label: "额度", render: row => `${row.service_id ?? "unknown"} · ${row.quantity ?? "0"} ${row.unit_code ?? "unit"}` },
          { key: "status", label: "状态", render: row => `${statusLabel(row.status, model?.statusCatalog)} · v${row.version ?? 0}` },
          { key: "source", label: "来源", render: row => row.source_ref_hash ? `${row.source_ref_hash.slice(0, 12)}…` : row.acquisition_method ?? "—" },
        ]} rowActions={canManageQuotas && model?.inspectedSchoolId ? row => [
          {
            label: "调整当前额度",
            onClick: () => quotaAdjustCommand(row),
          },
          {
            label: "撤销当前额度",
            onClick: () => quotaCloseCommand("撤销当前额度", row, "revoke"),
          },
          {
            label: "过期当前额度",
            onClick: () => quotaCloseCommand("过期当前额度", row, "expire"),
          },
        ] : undefined}/>
      </div>}
    </Section>}
    {(root === "home" || root === "usage") && <Section title="学校用量与任务" subtitle={`只读当前选择学校 ${model?.inspectedSchoolId || "（无）"} 的 attempt 与待核对任务；不展示学校私有正文。`}>
      <div className="section-grid">
        <DataTable rows={usageRows} searchLabel="搜索用量 attempt" columns={[
          { key: "attempt", label: "Attempt", render: row => row.attempt_id ?? row.id },
          { key: "service", label: "服务", render: row => row.service_id ?? "unknown" },
          { key: "status", label: "状态", render: row => statusLabel(row.status, model?.statusCatalog) },
          { key: "units", label: "单位", render: row => `${row.settled_units ?? "0"}/${row.reserved_units ?? "0"} ${row.unit_code ?? "unit"}` },
        ]} onOpen={row => openUsageDetail(row.id)} openLabel={row => `查看 ${row.attempt_id ?? row.id} 详情`}/>
        <DataTable rows={jobRows} searchLabel="搜索待核对任务" columns={[
          { key: "attempt", label: "Attempt", render: row => row.attempt_id ?? row.id },
          { key: "service", label: "服务", render: row => row.service_id ?? "unknown" },
          { key: "status", label: "状态", render: row => statusLabel(row.status, model?.statusCatalog) },
          { key: "units", label: "单位", render: row => `${row.settled_units ?? "0"}/${row.reserved_units ?? "0"} ${row.unit_code ?? "unit"}` },
        ]} onOpen={row => openUsageDetail(row.id)} openLabel={row => `查看 ${row.attempt_id ?? row.id} 任务详情`}/>
      </div>
    </Section>}
    {(root === "home" || root === "audit" || root === "authz-audit") && <Section title="审计与成本" subtitle="成本为 OMS-only 只读状态；不得从租户额度或用量推导。">
      {model?.cost.notice && <Notice tone="info">{model.cost.notice}</Notice>}
      <div className="section-grid">
        <DataTable rows={auditRows} searchLabel="搜索审计" columns={[
          { key: "action", label: "动作", render: row => row.action ?? row.id },
          { key: "result", label: "结果", render: row => statusLabel(row.result, model?.statusCatalog) },
          { key: "request", label: "请求", render: row => row.request_id ?? "—" },
        ]} onOpen={row => openDetail("audit", row.id)} openLabel={row => `查看 ${row.action ?? row.id} 审计详情`}/>
        <DetailGrid rows={[
          { label: "成本状态", value: statusLabel(model?.cost.status, model?.statusCatalog) },
          { label: "成本记录", value: String(model?.cost.costs?.length ?? 0) },
        ]}/>
      </div>
    </Section>}
    {(root === "home" || root === "skills") && <Section title="Skill 清单" subtitle="用于首个 Agent 接入前的 OMS 维护视图；review、publish、grant 均按 ops.skills.* 权限显隐。">
      <DataTable rows={skillRows} searchLabel="搜索 Skill" columns={[
        { key: "name", label: "Skill", render: row => row.name ?? row.id ?? "unknown" },
        { key: "status", label: "状态", render: row => row.status ?? "unknown" },
        { key: "revision", label: "版本", render: row => `r${row.published_version ?? row.published_revision ?? row.latest_version ?? row.latest_revision ?? 0}` },
        { key: "desc", label: "说明", render: row => row.description ?? "—" },
      ]} rowActions={(canReviewSkills || canPublishSkills || canGrantSkills) ? row => {
        const name = row.name ?? row.id ?? "";
        const revisionId = row.revision_id ?? row.published_revision_id ?? row.id ?? "";
        const sha = row.sha256 ?? "";
        const latestVersion = row.latest_version ?? row.latest_revision ?? row.published_version ?? row.published_revision ?? 0;
        return [
          {
            label: "查看 Skill 详情",
            onClick: () => openDetail("skills", row.id),
          },
          ...(canReviewSkills && revisionId && /^[0-9a-f]{64}$/.test(sha) ? [{
            label: "批准 Skill",
            onClick: () => runCommand("批准 Skill", `/api/v1/oms/skills/revisions/${encodeURIComponent(revisionId)}/review`, {
              expected_sha256: sha,
              approved: true,
              reason,
              code_review_evidence: "oms-formal-ui",
            }),
          }] : []),
          ...(canPublishSkills && revisionId ? [{
            label: "发布 Skill",
            onClick: () => runCommand("发布 Skill", `/api/v1/oms/skills/revisions/${encodeURIComponent(revisionId)}/publish`, {
              expected_version: latestVersion,
              reason,
            }),
          }] : []),
          ...(canGrantSkills && name && model?.inspectedSchoolId ? [{
            label: "授权首个学校 Skill",
            onClick: () => runCommand("授权首个学校 Skill", `/api/v1/oms/skills/${encodeURIComponent(name)}/schools/${encodeURIComponent(model.inspectedSchoolId)}/grant`, {
              expected_grant_version: 0,
              expires_at: "9998-01-01T00:00:00Z",
              reason,
            }),
          }] : []),
        ];
      } : undefined} onOpen={!(canReviewSkills || canPublishSkills || canGrantSkills) ? row => openDetail("skills", row.id) : undefined} openLabel={row => `查看 ${row.name ?? row.id} 详情`}/>
    </Section>}
    {formOpen === "model-draft-json" && <FormModal title="保存模型草稿 JSON" onClose={closeForm}>
      <div className="side-panel">
        <Notice tone="warn">保存会替换当前模型草稿版本；Secret 必须使用 env: 引用，后端会拒绝明文凭据。</Notice>
        <label className="form-field">模型草稿 JSON
          <textarea aria-label="模型草稿 JSON" value={modelDraftJson} onChange={event => { setModelDraftJson(event.target.value); setFormError(""); }} spellCheck={false}/>
        </label>
        {formError && <Notice tone="bad">{formError}</Notice>}
        <div className="form-actions">
          <Button variant="primary" onClick={() => { void saveModelDraftJson(); }}>保存模型草稿</Button>
          <Button onClick={closeForm}>取消</Button>
        </div>
      </div>
    </FormModal>}
    {formOpen === "provider-settings-json" && <FormModal title="导入 Provider 设置 JSON" onClose={closeForm}>
      <div className="side-panel">
        <Notice tone="warn">请提交完整 Provider 设置目标 JSON；Dry-run 只校验结构与 Secret 引用，不发布真实生效版本。</Notice>
        <label className="form-field">Provider 设置 JSON
          <textarea aria-label="Provider 设置 JSON" value={providerSettingsJson} onChange={event => { setProviderSettingsJson(event.target.value); setFormError(""); }} spellCheck={false}/>
        </label>
        {formError && <Notice tone="bad">{formError}</Notice>}
        <div className="form-actions">
          <Button onClick={() => { void dryRunProviderSettingsJson(); }}>Dry-run Provider 设置</Button>
          <Button variant="primary" onClick={() => { void saveProviderSettingsJson(); }}>保存 Provider 草稿</Button>
          <Button onClick={closeForm}>取消</Button>
        </div>
      </div>
    </FormModal>}
    {detailId && detailContent && <Drawer title={`详情 · ${detailTitle || detailId}`} onClose={closeDetail}>
      {detailContent}
    </Drawer>}
  </>);
}
