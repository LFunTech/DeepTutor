/** @type {import('next').NextConfig} */
const config = {
  output: "standalone",
  transpilePackages: ["@deeptutor/admin-ui", "@deeptutor/api-contracts", "@deeptutor/branding", "@deeptutor/service-components"],
};

export default config;
