/** @vitest-environment node */

import { renderToString } from "react-dom/server";
import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import OmsPrototype from "../apps/oms/src/OmsPrototype";
import TmsPrototype from "../apps/tms/src/TmsPrototype";

let pathname = "/oms/prototype";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

describe("OMS 服务端首屏渲染", () => {
  it.each([
    ["/oms/prototype", "工作台"],
    ["/oms/prototype/audit", "审计与治理"],
    ["/oms/prototype/tenants", "学校与权益"],
    ["/oms/prototype/services", "模型与服务"],
    ["/oms/prototype/skills", "Skills"],
    ["/oms/prototype/supply", "服务供给"],
    ["/oms/prototype/usage", "用量与运行"],
    ["/oms/prototype/services/llm/models", "对话模型"],
  ])("%s 无浏览器全局对象时仍可渲染", (route, expected) => {
    pathname = route;
    expect(renderToString(<OmsPrototype/>)).toContain(expected);
  });
});

describe("TMS 服务端首屏渲染", () => {
  it.each([
    ["/tms/prototype/demo-school", "工作台"],
    ["/tms/prototype/demo-school/apps", "应用与接入"],
    ["/tms/prototype/demo-school/services", "可用服务"],
    ["/tms/prototype/demo-school/quotas", "配额清单"],
    ["/tms/prototype/demo-school/knowledge", "知识与内容"],
    ["/tms/prototype/demo-school/skills", "Skills"],
    ["/tms/prototype/demo-school/usage", "用量与记录"],
  ])("%s 无浏览器全局对象时仍可渲染", (route, expected) => {
    pathname = route;
    expect(renderToString(<TmsPrototype schoolCode="demo-school"/>)).toContain(expected);
  });
});

it("审计分支避免含中文的超长源码行触发 Next.js 错误叠层高亮崩溃", () => {
  const source = readFileSync(new URL("../apps/oms/src/OmsPrototype.tsx", import.meta.url), "utf8");
  const auditBranch = source.split('} else if (root === "audit") {')[1]?.split('} else { content =')[0] ?? "";
  expect(auditBranch).not.toBe("");
  expect(Math.max(...auditBranch.split("\n").map(line => Buffer.byteLength(line, "utf8")))).toBeLessThan(180);
});
