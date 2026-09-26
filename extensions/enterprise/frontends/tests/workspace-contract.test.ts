import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { CONTRACT_VERSION } from "@deeptutor/api-contracts";

type PackageManifest = { version: string; dependencies?: Record<string, string> };
const packageNames = ["api-contracts", "admin-ui", "branding", "service-components"] as const;
const appNames = ["oms", "tms"] as const;

function manifest(path: string): PackageManifest {
  return JSON.parse(readFileSync(`${process.cwd()}/${path}/package.json`, "utf8")) as PackageManifest;
}

describe("OMS/TMS 共享包版本契约", () => {
  it("两个独立应用及共享组件固定在同一契约版本，不能静默失配", () => {
    for (const name of packageNames) {
      const current = manifest(`packages/${name}`);
      expect(current.version, name).toBe(CONTRACT_VERSION);
      for (const [dependency, version] of Object.entries(current.dependencies ?? {})) {
        if (dependency.startsWith("@deeptutor/")) expect(version, `${name} -> ${dependency}`).toBe(CONTRACT_VERSION);
      }
    }
    for (const name of appNames) {
      const current = manifest(`apps/${name}`);
      expect(current.version, name).toBe(CONTRACT_VERSION);
      for (const dependency of ["@deeptutor/api-contracts", "@deeptutor/admin-ui", "@deeptutor/branding", "@deeptutor/service-components"]) {
        expect(current.dependencies?.[dependency], `${name} -> ${dependency}`).toBe(CONTRACT_VERSION);
      }
    }
  });
});
