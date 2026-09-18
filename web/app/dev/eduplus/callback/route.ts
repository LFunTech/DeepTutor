import { NextRequest, NextResponse } from "next/server";

const DEMO_CALLBACK_PATH = "/api/v1/auth/eduplus2/demo/callback";

export function GET(request: NextRequest): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = DEMO_CALLBACK_PATH;
  return NextResponse.redirect(url, 307);
}
