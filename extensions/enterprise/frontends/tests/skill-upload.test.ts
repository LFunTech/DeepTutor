import { describe, expect, it, vi } from "vitest";
import { inspectSkillPackage } from "@deeptutor/service-components";
import { validateSkillFile } from "../apps/tms/src/skill-upload";
import { skillZip, zipEntries } from "./skill-zip-fixture";

describe("Skill ZIP 原型预检", () => {
  it("只接受完整 ZIP，不接受单独 SKILL.md", async () => {
    expect(await validateSkillFile(skillZip("demo", "说明", "执行说明"))).toBeNull();
    expect(await validateSkillFile(zipEntries([{ name: "SKILL.md", content: "---\nname: demo\ndescription: 根目录包\n---\n\n正文" }, { name: "references/guide.md", content: "参考" }]))).toBeNull();
    expect(await validateSkillFile(new File(["---\nname: demo\n---"], "SKILL.md"))).toMatch(/ZIP/);
  });

  it("必须读取包内 SKILL.md，而非仅凭 ZIP 文件列表通过", async () => {
    expect(await validateSkillFile(zipEntries([{ name: "demo/SKILL.md", content: "not YAML" }]))).toMatch(/SKILL.md|frontmatter/);
    expect(await validateSkillFile(zipEntries([{ name: "demo/SKILL.md", content: "---\nname: demo\n---\n\n说明" }]))).toMatch(/description/);
    expect(await validateSkillFile(zipEntries([{ name: "wrong/SKILL.md", content: "---\nname: demo\ndescription: 说明\n---\n\n正文" }]))).toMatch(/目录名/);
  });

  it("保留合法参考文件与受控文本脚本，拒绝危险路径和重复条目", async () => {
    expect(await validateSkillFile(skillZip("demo", "说明", "执行说明", [
      { name: "demo/references/guide.md", content: "参考资料" },
      { name: "demo/scripts/run.sh", content: "echo ok" },
    ]))).toBeNull();
    expect(await validateSkillFile(zipEntries([{ name: "../SKILL.md", content: "bad" }]))).toMatch(/路径/);
    expect(await validateSkillFile(zipEntries([{ name: "demo/SKILL.md", content: "a" }, { name: "demo/SKILL.md", content: "b" }]))).toMatch(/重复/);
  });

  it("解析压缩 ZIP 的版本、正文和资源，不接受未审查的自动注入", async () => {
    const file = zipEntries([
      { name: "demo/SKILL.md", content: "---\nname: demo\ndescription: 压缩包说明\nversion: 1.2.3\ntags: [teaching]\nrequires:\n  bins: [git]\nmetadata:\n  author: 学校团队\n---\n\n# 操作说明" },
      { name: "demo/references/guide.md", content: "参考" },
    ], "demo.zip", true);
    const parsed = await inspectSkillPackage(file);
    expect(parsed).toMatchObject({ name: "demo", description: "压缩包说明", body: "# 操作说明", authorVersion: "1.2.3", tags: ["teaching"], files: ["SKILL.md", "references/guide.md"] });
    expect(parsed.requires).toContain("git");
    expect(parsed.frontmatter.metadata).toEqual({ author: "学校团队" });
    expect(await validateSkillFile(zipEntries([{ name: "demo/SKILL.md", content: "---\nname: demo\ndescription: 说明\nalways: true\n---\n\n正文" }]))).toMatch(/always/);
  });

  it("拒绝不允许的文件类型及损坏的 ZIP 内容", async () => {
    expect(await validateSkillFile(skillZip("demo", "说明", "正文", [{ name: "demo/scripts/payload.exe", content: "x" }]))).toMatch(/文件类型/);
    const valid = skillZip("demo", "说明", "正文");
    const altered = new Uint8Array(await valid.arrayBuffer());
    altered[altered.indexOf("-".charCodeAt(0)) + 1] ^= 1;
    expect(await validateSkillFile(new File([altered], "demo.zip"))).toMatch(/校验|损坏|目录/);
  });

  it("拒绝包内伪造的归属状态与疑似 ZIP 膨胀，不把缺失运行条件冒充就绪", async () => {
    expect(await validateSkillFile(zipEntries([{ name: "demo/SKILL.md", content: "---\nname: demo\ndescription: 说明\nowner: global\nstatus: 已发布\n---\n\n正文" }]))).toMatch(/归属|状态/);
    expect(await validateSkillFile(zipEntries([{ name: "demo/SKILL.md", content: `---\nname: demo\ndescription: 说明\n---\n\n${"a".repeat(300_000)}` }], "demo.zip", true))).toMatch(/膨胀|超限/);
    const parsed = await inspectSkillPackage(skillZip("demo", "说明", "正文"));
    expect(parsed.requires).toBe("未声明");
  });

  it("把缺失 SKILL.md 与 YAML 错误明确归为内容格式，而非安全问题", async () => {
    const missing = await validateSkillFile(zipEntries([{ name: "demo/references/guide.md", content: "参考" }]));
    expect(missing).toMatch(/包结构问题.*未找到.*SKILL\.md.*根目录/);
    expect(missing).not.toMatch(/安全|危险/);
    const malformed = await validateSkillFile(zipEntries([{ name: "demo/SKILL.md", content: "---\nname: [\ndescription: 说明\n---\n\n正文" }]));
    expect(malformed).toMatch(/SKILL\.md 格式问题.*YAML.*第 \d+ 行/);
    expect(malformed).not.toMatch(/安全|危险/);
  });

  it("路径与辅助文件错误指出具体条目、原因和处理方法", async () => {
    const cases = [
      { name: "../SKILL.md", content: "x", expected: /路径安全限制.*\.\.\/SKILL\.md.*上级目录/ },
      { name: "demo/.DS_Store", content: "x", expected: /包内容问题.*\.DS_Store.*移除/ },
      { name: "__MACOSX/._demo", content: "x", expected: /包内容问题.*__MACOSX.*移除/ },
      { name: "./demo/SKILL.md", content: "x", expected: /包结构问题.*\.\/demo\/SKILL\.md.*重新打包/ },
    ];
    for (const { name, content, expected } of cases) {
      expect(await validateSkillFile(zipEntries([{ name, content }]))).toMatch(expected);
    }
  });

  it("重复文件、类型不兼容和损坏内容也指出发生问题的条目", async () => {
    expect(await validateSkillFile(zipEntries([{ name: "demo/SKILL.md", content: "a" }, { name: "demo/SKILL.md", content: "b" }]))).toMatch(/重复文件.*demo\/SKILL\.md/);
    expect(await validateSkillFile(skillZip("demo", "说明", "正文", [{ name: "demo/scripts/a.exe", content: "x" }]))).toMatch(/文件类型问题.*demo\/scripts\/a\.exe/);
    const valid = skillZip("demo", "说明", "正文");
    const changed = new Uint8Array(await valid.arrayBuffer());
    const marker = new TextEncoder().encode("description: ");
    const start = changed.findIndex((_, index) => marker.every((byte, offset) => changed[index + offset] === byte));
    expect(start).toBeGreaterThan(0);
    changed[start + marker.length] ^= 1;
    expect(await validateSkillFile(new File([changed], "demo.zip"))).toMatch(/ZIP 数据损坏.*demo\/SKILL\.md.*校验/);
  });

  it("浏览器不支持 ZIP 解压能力时不误报压缩包损坏", async () => {
    const file = zipEntries([{ name: "demo/SKILL.md", content: "---\nname: demo\ndescription: 说明\n---\n\n正文" }], "demo.zip", true);
    vi.stubGlobal("DecompressionStream", class { constructor() { throw new TypeError("unsupported format"); } });
    try {
      const error = await validateSkillFile(file);
      expect(error).toMatch(/浏览器兼容性问题.*ZIP 解压/);
      expect(error).not.toMatch(/损坏|安全/);
    } finally { vi.unstubAllGlobals(); }
  });

  it("文件名编码错误指出条目位置并提示重新生成 ZIP", async () => {
    const valid = skillZip("demo", "说明", "正文");
    const bytes = new Uint8Array(await valid.arrayBuffer());
    const view = new DataView(bytes.buffer);
    const centralOffset = view.getUint32(bytes.length - 22 + 16, true);
    bytes[centralOffset + 46] = 0xff;
    expect(await validateSkillFile(new File([bytes], "demo.zip"))).toMatch(/ZIP 文件名编码问题.*第 1 个条目.*UTF-8.*重新生成/);
  });

  it("拒绝伪造的 ZIP、重复 SKILL.md 与不完整 YAML", async () => {
    expect(await validateSkillFile(new File(["not a zip"], "demo.zip"))).toMatch(/ZIP 格式问题/);
    expect(await validateSkillFile(zipEntries([
      { name: "demo/SKILL.md", content: "---\nname: demo\ndescription: 说明\n---\n\n正文" },
      { name: "demo/references/SKILL.md", content: "重复" },
    ]))).toMatch(/找到 2 个 SKILL\.md/);
    expect(await validateSkillFile(zipEntries([{ name: "demo/SKILL.md", content: "---\nname: demo\nname: other\ndescription: 说明\n---\n\n正文" }]))).toMatch(/SKILL\.md 格式问题.*YAML/);
    expect(await validateSkillFile(zipEntries([{ name: "demo/SKILL.md", content: "---\nname: demo\ndescription: 说明\nstatus: 已发布\n---\n\n正文" }]))).toMatch(/包规则问题.*status/);
  });

  it("分别指出符号链接和加密文件，不把两者混为同一错误", async () => {
    const original = skillZip("demo", "说明", "正文");
    const symlink = new Uint8Array(await original.arrayBuffer());
    const linkView = new DataView(symlink.buffer);
    const linkCentral = linkView.getUint32(symlink.length - 22 + 16, true);
    linkView.setUint32(linkCentral + 38, 0xa0000000, true);
    expect(await validateSkillFile(new File([symlink], "demo.zip"))).toMatch(/文件安全限制.*demo\/SKILL\.md.*符号链接/);

    const encrypted = new Uint8Array(await original.arrayBuffer());
    const encryptedView = new DataView(encrypted.buffer);
    const encryptedCentral = encryptedView.getUint32(encrypted.length - 22 + 16, true);
    encryptedView.setUint16(encryptedCentral + 8, 1, true);
    expect(await validateSkillFile(new File([encrypted], "demo.zip"))).toMatch(/ZIP 安全限制.*demo\/SKILL\.md.*加密/);
  });
});
