import { fileURLToPath } from "node:url";

/** @type {import('next').NextConfig} */
const config = {
  output: "standalone",
  allowedDevOrigins: ["deeptutor.lfun.pub"],
  turbopack: { root: fileURLToPath(new URL("../../", import.meta.url)) },
  transpilePackages: ["@deeptutor/admin-ui", "@deeptutor/api-contracts", "@deeptutor/branding", "@deeptutor/service-components"],
  async rewrites() {
    const apiOrigin = process.env.DEEPTUTOR_ENTERPRISE_API_ORIGIN || "http://127.0.0.1:8001";
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default config;
