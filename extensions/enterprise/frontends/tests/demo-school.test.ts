import { describe, expect, it } from "vitest";
import { demoSchoolContext, isDemoSchoolRoute } from "../apps/tms/src/demo-school";

describe("TMS 原型学校上下文", () => {
  it("仅使用配对且格式有效的部署参数确定学校路由", () => {
    expect(demoSchoolContext({ NODE_ENV: "development", TMS_DEMO_SCHOOL_CODE: "jygjzx", TMS_DEMO_TENANT_ID: "92" }))
      .toEqual({ schoolCode: "jygjzx", tenantId: "92" });
    expect(demoSchoolContext({ NODE_ENV: "development", TMS_DEMO_SCHOOL_CODE: "jygjzx" }))
      .toEqual({ schoolCode: "demo-school" });
    expect(demoSchoolContext({ NODE_ENV: "development", TMS_DEMO_SCHOOL_CODE: "../other", TMS_DEMO_TENANT_ID: "92" }))
      .toEqual({ schoolCode: "demo-school" });
    expect(demoSchoolContext({ NODE_ENV: "production", TMS_DEMO_SCHOOL_CODE: "jygjzx", TMS_DEMO_TENANT_ID: "92" }))
      .toEqual({ schoolCode: "demo-school" });
  });

  it("路径 code 只能匹配受控演示学校，不能选择其他学校", () => {
    const context = { schoolCode: "jygjzx", tenantId: "92" };
    expect(isDemoSchoolRoute("jygjzx", context)).toBe(true);
    expect(isDemoSchoolRoute("other", context)).toBe(false);
    expect(isDemoSchoolRoute("jygjzx%2fother", context)).toBe(false);
  });
});
