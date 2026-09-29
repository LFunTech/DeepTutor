import { fileURLToPath } from "node:url";

/** @type {import('next').NextConfig} */
const config = {
  output: "standalone",
  basePath: "/tms",
  turbopack: { root: fileURLToPath(new URL("../../", import.meta.url)) },
  transpilePackages: ["@deeptutor/admin-ui", "@deeptutor/api-contracts", "@deeptutor/branding", "@deeptutor/service-components"],
};

export default config;
