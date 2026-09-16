import test from "node:test";
import assert from "node:assert/strict";
import type { MasteryEvent } from "../lib/learning-api";
import { useMasteryPathActivity } from "../hooks/useMasteryPathActivity";

test("actual hook recovers same-revision pages using REST only and rebuilds socket with durable cursor", async () => {
  const { JSDOM } = require("jsdom");
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost", pretendToBeVisual: true });
  const saved = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document, navigator: dom.window.navigator, IS_REACT_ACT_ENVIRONMENT: true })) {
    saved.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  const { renderHook, act } = await import("@testing-library/react");
  const sockets: FakeSocket[] = [];
  class FakeSocket {
    readyState = 0;
    sent: string[] = [];
    onopen: (() => void) | null = null;
    onclose: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onerror: (() => void) | null = null;
    constructor() { sockets.push(this); }
    send(data: string) { this.sent.push(data); }
    open() { this.readyState = 1; this.onopen?.(); }
    close() { if (this.readyState !== 3) { this.readyState = 3; this.onclose?.(); } }
  }
  const oldSocket = globalThis.WebSocket, oldFetch = globalThis.fetch;
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket;
  const events: MasteryEvent[] = Array.from({ length: 450 }, (_, index) => ({ id: index + 1, revision: 7, event_type: "event", payload: {}, session_id: "", turn_id: "", created_at: 1 }));
  const requests: URL[] = [];
  globalThis.fetch = async (input) => {
    const url = new URL(String(input), "http://localhost"); requests.push(url);
    const cursor = url.searchParams.get("cursor");
    const start = cursor ? Number(cursor.slice(1)) : Number(url.searchParams.get("after_revision")) >= 7 ? 450 : 0;
    const page = events.slice(start, start + 200);
    const end = start + page.length;
    return new Response(JSON.stringify({ events: page, next_cursor: end < 450 ? `c${end}` : null, cursor: `c${end}` }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  let unmount: (() => void) | undefined;
  try {
    const hook = renderHook(({ path }: { path: string | null }) => useMasteryPathActivity(path), { initialProps: { path: "p" } as { path: string | null } });
    unmount = hook.unmount;
    await act(async () => {
      sockets[0].open();
      sockets[0].onmessage?.({ data: JSON.stringify({ type: "subscribed", path_id: "p", revision: 7, events: events.slice(0, 200), cursor: "c200", next_cursor: "c200" }) });
    });
    assert.equal(hook.result.current.events.length, 200);
    await act(async () => { sockets[0].close(); await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.equal(requests[0].searchParams.get("cursor"), "c200");
    assert.equal(hook.result.current.events.length, 450);
    assert.equal(new Set(hook.result.current.events.map((e) => e.id)).size, 450);
    await act(async () => { hook.result.current.refresh(); await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.equal(requests.at(-1)!.searchParams.get("cursor"), "c450");
    hook.rerender({ path: null }); hook.rerender({ path: "p" });
    await act(async () => { sockets.at(-1)!.open(); });
    assert.equal(JSON.parse(sockets.at(-1)!.sent[0]).cursor, "c450");
  } finally {
    unmount?.(); globalThis.WebSocket = oldSocket; globalThis.fetch = oldFetch;
    for (const [key, descriptor] of saved) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
    dom.window.close();
  }
});
