import nextConfig from "eslint-config-next";

export default [
  ...nextConfig,
  { rules: { "@next/next/no-html-link-for-pages": "off" } },
  { ignores: ["**/.next/**", "**/node_modules/**", "**/next-env.d.ts"] },
];
