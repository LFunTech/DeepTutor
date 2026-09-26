export type DemoSchoolContext = { schoolCode: string; tenantId?: string };

const DEFAULT_SCHOOL_CODE = "demo-school";
const SCHOOL_CODE = /^[a-z0-9][a-z0-9_-]{0,63}$/;

export function demoSchoolContext(env: NodeJS.ProcessEnv): DemoSchoolContext {
  const schoolCode = env.TMS_DEMO_SCHOOL_CODE?.trim();
  const tenantId = env.TMS_DEMO_TENANT_ID?.trim();
  if (env.NODE_ENV === "development" && schoolCode && SCHOOL_CODE.test(schoolCode) && schoolCode !== DEFAULT_SCHOOL_CODE && tenantId && /^\d+$/.test(tenantId)) {
    return { schoolCode, tenantId };
  }
  return { schoolCode: DEFAULT_SCHOOL_CODE };
}

export function isDemoSchoolRoute(code: string, context: DemoSchoolContext): boolean {
  return SCHOOL_CODE.test(code) && code === context.schoolCode;
}
