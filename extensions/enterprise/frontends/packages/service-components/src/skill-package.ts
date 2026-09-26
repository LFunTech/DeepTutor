/// <reference path="./js-yaml.d.ts" />

import { JSON_SCHEMA, load } from "js-yaml";

export type SkillPackageInspection = {
  name: string;
  description: string;
  body: string;
  tags: string[];
  requires: string;
  authorVersion?: string;
  license?: string;
  compatibility?: string;
  allowedTools?: string;
  files: string[];
  archiveName: string;
  frontmatter: Record<string, unknown>;
};

export type SkillPackageRevision = {
  archive?: File;
  name: string;
  description: string;
  version: string;
  body: string;
  files: string[];
  reference: string;
  origin?: string;
  digest?: string;
  grants?: string[];
  frontmatter?: Record<string, unknown>;
};

type Entry = { name: string; size: number; compressed: number; method: number; crc: number; start: number };
const MAX_ARCHIVE = 20_000_000;
const MAX_TOTAL = 20_000_000;
const MAX_ENTRY = 1_000_000;
const MAX_FILES = 500;
const ALLOWED = new Set(["", ".md", ".markdown", ".txt", ".rst", ".py", ".js", ".mjs", ".ts", ".sh", ".rb", ".lua", ".r", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".csv", ".tsv", ".html", ".htm", ".css", ".xml", ".sql", ".jinja", ".j2", ".tmpl", ".template"]);
const decoder = new TextDecoder("utf-8", { fatal: true });

function invalid(message: string): never { throw new Error(message); }
function entryLabel(name: string): string {
  const visible = name.length > 120 ? `${name.slice(0, 120)}…` : name;
  return `条目 ${JSON.stringify(visible)}`;
}
function crc32(bytes: Uint8Array) {
  let value = 0xffffffff;
  for (const byte of bytes) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit++) value = (value >>> 1) ^ (value & 1 ? 0xedb88320 : 0);
  }
  return (value ^ 0xffffffff) >>> 0;
}
function readName(bytes: Uint8Array, location: string) {
  try { return decoder.decode(bytes); } catch { return invalid(`ZIP 文件名编码问题：${location} 不是 UTF-8；请使用 UTF-8 文件名重新生成 ZIP。`); }
}
function parseEntries(bytes: Uint8Array): Entry[] {
  if (bytes.length < 22) invalid("ZIP 格式问题：文件过短，不是完整的 ZIP；请重新生成压缩包。");
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let end = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
    if (view.getUint32(i, true) === 0x06054b50 && i + 22 + view.getUint16(i + 20, true) === bytes.length) { end = i; break; }
  }
  if (end < 0) invalid("ZIP 格式问题：未找到完整的 ZIP 结束记录；请确认文件没有截断并重新压缩。");
  const count = view.getUint16(end + 10, true);
  const centralSize = view.getUint32(end + 12, true);
  let offset = view.getUint32(end + 16, true);
  if (count < 1) invalid("包结构问题：ZIP 内没有文件；请放入包含 SKILL.md 的 Skill 目录后重新压缩。");
  if (count > MAX_FILES) invalid(`包容量限制：ZIP 包含 ${count} 个条目，最多允许 ${MAX_FILES} 个；请删减文件后重新打包。`);
  if (view.getUint16(end + 4, true) !== 0 || view.getUint16(end + 6, true) !== 0 || view.getUint16(end + 8, true) !== count || offset === 0xffffffff || centralSize === 0xffffffff || offset + centralSize !== end) invalid("ZIP 格式问题：目录位置或条目数量记录不一致；请重新生成压缩包。");
  const centralStart = offset;
  const entries: Entry[] = [];
  const seen = new Set<string>();
  let total = 0;
  for (let index = 0; index < count; index++) {
    if (offset + 46 > end || view.getUint32(offset, true) !== 0x02014b50) invalid(`ZIP 格式问题：第 ${index + 1} 个条目的目录记录损坏；请重新生成压缩包。`);
    const flags = view.getUint16(offset + 8, true);
    const method = view.getUint16(offset + 10, true);
    const crc = view.getUint32(offset + 16, true);
    const compressed = view.getUint32(offset + 20, true);
    const size = view.getUint32(offset + 24, true);
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const mode = view.getUint32(offset + 38, true) >>> 16;
    const localOffset = view.getUint32(offset + 42, true);
    if (offset + 46 + nameLength + extraLength + commentLength > end) invalid(`ZIP 格式问题：第 ${index + 1} 个条目的目录记录不完整；请重新生成压缩包。`);
    const name = readName(bytes.subarray(offset + 46, offset + 46 + nameLength), `第 ${index + 1} 个条目`);
    offset += 46 + nameLength + extraLength + commentLength;
    const parts = name.split("/");
    const label = entryLabel(name);
    if (!name) invalid(`包结构问题：第 ${index + 1} 个 ZIP 条目没有文件名；请重新打包。`);
    if (name.startsWith("__MACOSX/") || parts.some(part => part === ".DS_Store" || part.startsWith("._"))) invalid(`包内容问题：${label} 是 macOS 自动生成的辅助文件；请移除后重新打包。`);
    if (name.startsWith("./") || parts.some(part => part === ".")) invalid(`包结构问题：${label} 含有多余的 ./ 路径；请从 Skill 目录重新打包。`);
    if (name.startsWith("/") || name.includes("\\") || name.includes(":") || parts.includes("..")) invalid(`路径安全限制：${label} 使用绝对路径、反斜杠、盘符或上级目录（..）；请只保留 Skill 目录内的相对路径。`);
    if (/[\x00-\x1f\x7f]/.test(name)) invalid(`路径安全限制：${label} 含有控制字符；请重命名文件后重新打包。`);
    if (parts.some((part, partIndex) => !part && partIndex !== parts.length - 1)) invalid(`包结构问题：${label} 含有重复的 /；请规范目录路径后重新打包。`);
    if (parts.some(part => part.startsWith("."))) invalid(`包内容问题：${label} 是隐藏文件或隐藏目录；请移除后重新打包。`);
    const key = name.toLocaleLowerCase();
    if (seen.has(key)) invalid(`重复文件：${label} 在 ZIP 中出现多次（文件名不区分大小写）；请只保留一个。`);
    seen.add(key);
    if ((mode & 0xf000) === 0xa000) invalid(`文件安全限制：${label} 是符号链接；请改为包内实际文件后重新打包。`);
    if (flags & 0x41) invalid(`ZIP 安全限制：${label} 已加密；请使用未加密的 Skill ZIP 包。`);
    if (method !== 0 && method !== 8) invalid(`ZIP 格式问题：${label} 使用不支持的压缩方式（${method}）；请重新生成标准 ZIP 包。`);
    if (size > MAX_ENTRY) invalid(`包容量限制：${label} 解压后超过单文件 1 MB 上限；请缩减文件内容。`);
    if (compressed > MAX_ARCHIVE) invalid(`包容量限制：${label} 的压缩数据超过 20 MB 上限；请缩减文件内容。`);
    if (size > 0 && size / Math.max(1, compressed) > 200) invalid(`ZIP 膨胀限制：${label} 的解压比例超过 200 倍；请检查并重新打包。`);
    total += size;
    if (total > MAX_TOTAL) invalid(`包容量限制：ZIP 解压后总大小超过 20 MB（检查到 ${label} 时超限）；请删减资源文件。`);
    if (localOffset + 30 > centralStart || view.getUint32(localOffset, true) !== 0x04034b50) invalid(`ZIP 格式问题：${label} 的文件记录损坏；请重新生成压缩包。`);
    const localNameLength = view.getUint16(localOffset + 26, true);
    const localExtraLength = view.getUint16(localOffset + 28, true);
    const start = localOffset + 30 + localNameLength + localExtraLength;
    if (start + compressed > centralStart || view.getUint16(localOffset + 6, true) !== flags || view.getUint16(localOffset + 8, true) !== method || readName(bytes.subarray(localOffset + 30, localOffset + 30 + localNameLength), `${label} 的本地文件名`) !== name) invalid(`ZIP 格式问题：${label} 的目录记录与文件记录不一致；请重新生成压缩包。`);
    if (!(flags & 8) && (view.getUint32(localOffset + 14, true) !== crc || view.getUint32(localOffset + 18, true) !== compressed || view.getUint32(localOffset + 22, true) !== size)) invalid(`ZIP 数据损坏：${label} 的大小或校验信息不一致；请重新生成压缩包。`);
    if (name.endsWith("/")) {
      if (size !== 0) invalid(`ZIP 格式问题：目录 ${label} 包含文件内容；请重新生成压缩包。`);
      continue;
    }
    const fileName = name.split("/").at(-1)!;
    const suffix = fileName.includes(".") ? `.${fileName.split(".").at(-1)!.toLowerCase()}` : "";
    if (!ALLOWED.has(suffix)) invalid(`文件类型问题：${label} 的 .${suffix.slice(1) || "无扩展名"} 类型不在 DeepTutor Skill 资源白名单内；请移除或转换为受支持的文本资源。`);
    entries.push({ name, size, compressed, method, crc, start });
  }
  if (offset !== end) invalid("ZIP 格式问题：目录长度与条目记录不一致；请重新生成压缩包。");
  return entries;
}

async function readEntry(bytes: Uint8Array, entry: Entry): Promise<Uint8Array> {
  const source = bytes.subarray(entry.start, entry.start + entry.compressed);
  let result: Uint8Array;
  if (entry.method === 0) result = source;
  else {
    if (typeof DecompressionStream === "undefined") invalid("浏览器兼容性问题：当前浏览器不支持 ZIP 解压预检；请换用支持的浏览器。");
    let decompressor: DecompressionStream;
    try { decompressor = new DecompressionStream("deflate-raw"); }
    catch { return invalid("浏览器兼容性问题：当前浏览器不支持 ZIP 解压所需的 deflate-raw 格式；请换用支持的浏览器。"); }
    try {
      const stream = new ReadableStream<Uint8Array<ArrayBuffer>>({ start(controller) { controller.enqueue(Uint8Array.from(source)); controller.close(); } });
      const reader = stream.pipeThrough(decompressor).getReader();
      const chunks: Uint8Array[] = [];
      let length = 0;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        length += value.length;
        if (length > entry.size || length > MAX_ENTRY) { await reader.cancel(); invalid(`ZIP 数据损坏：${entryLabel(entry.name)} 解压结果超过文件记录声明的大小；请重新生成压缩包。`); }
        chunks.push(value);
      }
      result = new Uint8Array(length);
      let position = 0;
      for (const chunk of chunks) { result.set(chunk, position); position += chunk.length; }
    } catch (error) {
      if (error instanceof Error && error.message.startsWith("ZIP 数据损坏：")) throw error;
      return invalid(`ZIP 数据损坏：${entryLabel(entry.name)} 无法解压；请检查文件并重新生成压缩包。`);
    }
  }
  if (result.length !== entry.size || crc32(result) !== entry.crc) invalid(`ZIP 数据损坏：${entryLabel(entry.name)} 的大小或 CRC 校验失败；请重新生成压缩包。`);
  return result;
}

export async function inspectSkillPackage(file: File): Promise<SkillPackageInspection> {
  if (!file.name.toLowerCase().endsWith(".zip")) invalid("文件格式问题：请选择完整的 Skill ZIP 包（.zip），不接受单独的 SKILL.md。");
  if (!file.size) invalid("文件格式问题：所选 ZIP 文件为空；请重新选择完整的 Skill 包。");
  if (file.size > MAX_ARCHIVE) invalid("包容量限制：ZIP 文件超过 20 MB；请缩减资源文件后重新打包。");
  const bytes = new Uint8Array(await file.arrayBuffer());
  const entries = parseEntries(bytes);
  const allSkillFiles = entries.filter(entry => entry.name === "SKILL.md" || entry.name.endsWith("/SKILL.md"));
  if (allSkillFiles.length === 0) invalid("包结构问题：未找到 SKILL.md；请将它放在 ZIP 根目录或唯一顶层 Skill 目录的根目录。");
  if (allSkillFiles.length > 1) invalid(`包结构问题：找到 ${allSkillFiles.length} 个 SKILL.md（如 ${entryLabel(allSkillFiles[0].name)}）；请只保留一个。`);
  const skillFiles = allSkillFiles.filter(entry => entry.name === "SKILL.md" || /^[^/]+\/SKILL\.md$/.test(entry.name));
  if (skillFiles.length !== 1) invalid(`包结构问题：${entryLabel(allSkillFiles[0].name)} 不在 ZIP 根目录或唯一顶层 Skill 目录中；请调整目录后重新打包。`);
  const root = skillFiles[0].name === "SKILL.md" ? "" : skillFiles[0].name.slice(0, -"SKILL.md".length);
  if (root) {
    const outside = entries.find(entry => !entry.name.startsWith(root));
    if (outside) invalid(`包结构问题：${entryLabel(outside.name)} 不在 ${entryLabel(root)} 内；ZIP 只能包含一个顶层 Skill 目录。`);
  }
  for (const entry of entries) {
    if (!root && entry.name !== "SKILL.md" && entry.name.split("/").length < 2) invalid(`包结构问题：${entryLabel(entry.name)} 位于 ZIP 根目录；资源文件应放在 references/、scripts/ 等子目录。`);
    await readEntry(bytes, entry);
  }
  let content: string;
  const skillBytes = await readEntry(bytes, skillFiles[0]);
  try { content = decoder.decode(skillBytes); } catch { return invalid("SKILL.md 格式问题：文件不是 UTF-8 文本；请另存为 UTF-8 后重新打包。"); }
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  if (!match) invalid("SKILL.md 格式问题：文件开头缺少完整的 YAML frontmatter（--- 分隔符）；请补齐后重新打包。");
  let metadata: unknown;
  try { metadata = load(match[1], { schema: JSON_SCHEMA }); } catch (error) {
    const mark = error && typeof error === "object" && "mark" in error ? (error as { mark?: { line?: number; column?: number } }).mark : undefined;
    const position = typeof mark?.line === "number" && typeof mark?.column === "number" ? `第 ${mark.line + 2} 行第 ${mark.column + 1} 列` : "内容";
    return invalid(`SKILL.md 格式问题：YAML ${position}无法解析；请检查附近的缩进、括号和引号。`);
  }
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) invalid("SKILL.md 格式问题：YAML frontmatter 必须是包含 name、description 的键值对象。");
  const value = metadata as Record<string, unknown>;
  const governanceField = Object.keys(value).find(actual => ["owner", "tenant_id", "tenantid", "status", "published", "authorized", "grants", "readiness", "review"].includes(actual.toLowerCase()));
  if (governanceField) invalid(`包规则问题：SKILL.md 不能声明 ${governanceField}；Skill 归属、授权和审核状态由平台管理，请移除该字段。`);
  const name = value.name;
  const description = value.description;
  if (typeof name !== "string" || name.length > 64 || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(name)) invalid("SKILL.md 格式问题：name 必须是 1–64 位小写字母、数字或连字符；请修改 SKILL.md。");
  if (root && root.slice(0, -1) !== name) invalid(`包结构问题：顶层目录名 ${JSON.stringify(root.slice(0, -1))} 与 SKILL.md 的 name ${JSON.stringify(name)} 不一致；请改名后重新打包。`);
  if (typeof description !== "string" || !description.trim() || description.length > 1024) invalid("SKILL.md 格式问题：description 必须是 1–1024 字符的非空说明；请修改 SKILL.md。");
  const body = content.slice(match[0].length).trim();
  if (!body) invalid("SKILL.md 格式问题：YAML frontmatter 后缺少 Markdown 说明正文；请补充正文。");
  if (value.always === true) invalid("使用限制：SKILL.md 中的 always: true 会自动注入内容，未经审查不能启用；请移除或改为 false。");
  if (value.tags !== undefined && (!Array.isArray(value.tags) || value.tags.some(tag => typeof tag !== "string"))) invalid("SKILL.md 格式问题：tags 必须是文本列表，例如 tags: [teaching]。");
  if (Array.isArray(value.tags) && value.tags.some(tag => !/^[a-z0-9][a-z0-9\- _]{0,31}$/.test(tag))) invalid("SKILL.md 格式问题：tags 中的标签不符合 DeepTutor 格式；请使用小写字母、数字、空格或连字符。");
  if (value.compatibility !== undefined && (typeof value.compatibility !== "string" || value.compatibility.length > 500)) invalid("SKILL.md 格式问题：compatibility 必须是 500 字符以内的文本。");
  if (value.license !== undefined && typeof value.license !== "string") invalid("SKILL.md 格式问题：license 必须是文本。");
  if (value["allowed-tools"] !== undefined && typeof value["allowed-tools"] !== "string") invalid("SKILL.md 格式问题：allowed-tools 必须是文本。");
  if (value.metadata !== undefined && (!value.metadata || typeof value.metadata !== "object" || Array.isArray(value.metadata) || Object.values(value.metadata).some(item => typeof item !== "string"))) invalid("SKILL.md 格式问题：metadata 必须是文本键值映射。");
  if (value.version !== undefined && typeof value.version !== "string") invalid("SKILL.md 格式问题：version 必须是文本。");
  if (value.requires !== undefined && (!value.requires || typeof value.requires !== "object" || Array.isArray(value.requires))) invalid("SKILL.md 格式问题：requires 必须是对象。");
  let frontmatter: Record<string, unknown>;
  try { frontmatter = JSON.parse(JSON.stringify(value)) as Record<string, unknown>; } catch { return invalid("SKILL.md 格式问题：YAML 不能包含循环引用；请检查锚点与别名。"); }
  const authorVersion = (value.version as string | undefined) ?? (value.metadata as Record<string, string> | undefined)?.version;
  return { name, description: description.trim(), body, tags: (value.tags as string[] | undefined) ?? [], requires: value.requires ? JSON.stringify(value.requires) : "未声明", authorVersion, license: value.license as string | undefined, compatibility: value.compatibility as string | undefined, allowedTools: value["allowed-tools"] as string | undefined, frontmatter, files: entries.map(entry => root ? entry.name.slice(root.length) : entry.name), archiveName: file.name };
}
