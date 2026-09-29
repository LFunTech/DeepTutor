"use client";

import { useCallback, useEffect, useState } from "react";
import { Notice, PageHead, StatePanel } from "@deeptutor/admin-ui";

type Props = {
  redirect?: (url: string) => void;
};

function appendLoginStatus(url: string, status: "ok" | "failed", reason?: string) {
  try {
    const base = typeof window === "undefined" ? "https://deeptutor.local" : window.location.origin;
    const absolute = /^[a-z][a-z0-9+.-]*:\/\//i.test(url);
    const target = new URL(url, base);
    target.searchParams.set("oms_login", status);
    if (reason) target.searchParams.set("reason", reason);
    return absolute ? target.toString() : target.pathname + target.search + target.hash;
  } catch {
    const separator = url.includes("?") ? "&" : "?";
    return `${url}${separator}oms_login=${status}${reason ? `&reason=${encodeURIComponent(reason)}` : ""}`;
  }
}

async function exchangeCode(params: URLSearchParams) {
  const response = await fetch("/api/v1/oms/auth/callback", {
    method: "POST",
    credentials: "include",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({
      code: params.get("code") ?? "",
      state: params.get("state") ?? "",
    }),
  });
  let body: { authenticated?: boolean; return_url?: string; detail?: string } = {};
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok || !body.authenticated) {
    throw new Error(body.detail || response.statusText || "oms_login_failed");
  }
  return body.return_url || "/oms";
}

export default function OmsAuthCallback({ redirect }: Props) {
  const [message, setMessage] = useState("正在完成 OMS 登录…");
  const [failed, setFailed] = useState(false);
  const doRedirect = useCallback(
    (url: string) => {
      if (redirect) redirect(url);
      else window.location.replace(url);
    },
    [redirect],
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const providerError = params.get("error");
    if (providerError) {
      doRedirect(appendLoginStatus("/oms", "failed", "authorization_denied"));
      return;
    }
    if (!params.get("code") || !params.get("state")) {
      doRedirect(appendLoginStatus("/oms", "failed", "code_or_state_missing"));
      return;
    }
    let cancelled = false;
    exchangeCode(params)
      .then((returnUrl) => {
        if (!cancelled) doRedirect(appendLoginStatus(returnUrl, "ok"));
      })
      .catch((error) => {
        if (cancelled) return;
        setFailed(true);
        setMessage(error instanceof Error ? error.message : "oms_login_failed");
      });
    return () => {
      cancelled = true;
    };
  }, [doRedirect]);

  return (
    <main className="content">
      <p className="eyebrow">智能体基座</p>
      <PageHead title="OMS 登录回调" description="前端接收 EduPlus2 授权码后，通过 BFF API 完成 token exchange。" />
      {failed ? (
        <Notice tone="warn">OMS 登录未完成：{message}</Notice>
      ) : (
        <StatePanel state="loading" message={message} />
      )}
    </main>
  );
}
