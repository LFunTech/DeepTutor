import { describe, expect, it } from "vitest";

import {
  OMS_SERVICE_INVENTORY,
  formatDemoFee,
  formatDemoFeeExact,
} from "@/features/oms-prototype/service-inventory";

describe("OMS 开发态原型的 DeepTutor 设置契约", () => {
  it("逐项覆盖现有八种模型目录服务且不捏造搜索模型", () => {
    expect(OMS_SERVICE_INVENTORY.map(entry => entry.service)).toEqual([
      "llm",
      "task",
      "embedding",
      "search",
      "tts",
      "stt",
      "imagegen",
      "videogen",
    ]);
    expect(OMS_SERVICE_INVENTORY.find(entry => entry.service === "search")?.modelFields).toEqual(
      [],
    );
    expect(OMS_SERVICE_INVENTORY.find(entry => entry.service === "task")?.note).toContain(
      "未单独配置时沿用对话模型",
    );
  });

  it("OMS 只读属性盘点不暴露密钥或配置写字段", () => {
    const values = OMS_SERVICE_INVENTORY.flatMap(entry => [
      ...entry.profileFields,
      ...entry.modelFields,
    ]);
    expect(values).not.toContain("api_key");
    expect(values).not.toContain("base_url");
    expect(values).not.toContain("extra_headers");
    expect(
      OMS_SERVICE_INVENTORY.find(entry => entry.service === "embedding")?.modelFields,
    ).toContain("send_dimensions");
    expect(OMS_SERVICE_INVENTORY.find(entry => entry.service === "stt")?.modelFields).not.toContain(
      "language",
    );
  });

  it("示例费用用整数运算并将缺失 usage 保持待核算", () => {
    expect(formatDemoFee(1_250_000, "12.345678")).toBe("¥15.43");
    expect(formatDemoFee(null, "12.345678")).toBe("待核算");
    expect(formatDemoFee(1_000_000, "invalid")).toBe("单价格式有误");
    expect(formatDemoFee(1_000_000, "1234567890123")).toBe("单价格式有误");
    expect(formatDemoFee(1_000, "4.999999")).toBe("¥0.00");
    expect(formatDemoFeeExact(1_000, "4.999999")).toBe("¥0.004999999");
    expect(formatDemoFeeExact(null, "4.999999")).toBe("待核算");
  });
});
