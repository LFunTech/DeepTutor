import http from "node:http";
import net from "node:net";

const host = process.env.FRONTEND_HOST || "0.0.0.0";
const port = Number.parseInt(process.env.FRONTEND_PORT || "3782", 10);
const targets = {
  backend: { host: "127.0.0.1", port: Number.parseInt(process.env.BACKEND_PORT || "8001", 10) },
  core: { host: "127.0.0.1", port: Number.parseInt(process.env.CORE_FRONTEND_PORT || "3785", 10) },
  oms: { host: "127.0.0.1", port: Number.parseInt(process.env.OMS_FRONTEND_PORT || "3783", 10) },
  tms: { host: "127.0.0.1", port: Number.parseInt(process.env.TMS_FRONTEND_PORT || "3784", 10) },
};

function targetFor(pathname = "/") {
  if (pathname === "/oms" || pathname.startsWith("/oms/")) return targets.oms;
  if (pathname === "/tms" || pathname.startsWith("/tms/")) return targets.tms;
  if (
    pathname === "/api" ||
    pathname.startsWith("/api/") ||
    pathname === "/ws" ||
    pathname.startsWith("/ws/") ||
    pathname === "/health" ||
    pathname.startsWith("/health/")
  ) return targets.backend;
  return targets.core;
}

function proxyHeaders(req, target) {
  return {
    ...req.headers,
    host: req.headers.host,
    "x-forwarded-host": req.headers["x-forwarded-host"] || req.headers.host || "",
    "x-forwarded-proto": req.headers["x-forwarded-proto"] || "http",
    "x-forwarded-for": [req.headers["x-forwarded-for"], req.socket.remoteAddress].filter(Boolean).join(", "),
    "x-deeptutor-frontend-target": `${target.host}:${target.port}`,
  };
}

const server = http.createServer((req, res) => {
  const target = targetFor(req.url || "/");
  const upstream = http.request({
    host: target.host,
    port: target.port,
    method: req.method,
    path: req.url,
    headers: proxyHeaders(req, target),
  }, (upstreamRes) => {
    res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
    upstreamRes.pipe(res);
  });
  upstream.on("error", (error) => {
    console.error("[Frontend:gateway] upstream request failed", req.url, error.message);
    if (!res.headersSent) res.writeHead(502, { "content-type": "application/json" });
    res.end(JSON.stringify({ detail: "frontend gateway upstream unavailable" }));
  });
  req.pipe(upstream);
});

server.on("upgrade", (req, socket, head) => {
  const target = targetFor(req.url || "/");
  const upstream = net.connect(target.port, target.host, () => {
    upstream.write(
      `${req.method} ${req.url} HTTP/${req.httpVersion}\r\n` +
      Object.entries(proxyHeaders(req, target)).map(([key, value]) => `${key}: ${value}`).join("\r\n") +
      "\r\n\r\n",
    );
    if (head.length > 0) upstream.write(head);
    socket.pipe(upstream).pipe(socket);
  });
  upstream.on("error", (error) => {
    console.error("[Frontend:gateway] upstream upgrade failed", req.url, error.message);
    socket.destroy();
  });
});

server.listen(port, host, () => {
  console.log(`[Frontend:gateway] 🚪 Listening on ${host}:${port}`);
});
