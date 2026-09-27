ARG NODE_IMAGE=node:22-bookworm
ARG NGINX_IMAGE=nginx:1.27-alpine

FROM ${NODE_IMAGE} AS builder

ARG NPM_REGISTRY=https://registry.npmjs.org/
ARG DOCS_SITE_URL
ARG DOCS_BASE_URL=/docs/

WORKDIR /app
COPY . .
RUN test -n "${DOCS_SITE_URL}" \
    && test "${DOCS_BASE_URL}" = "/docs/" \
    && npm config set registry "${NPM_REGISTRY}" \
    && npm ci --no-audit --no-fund \
    && npm run typecheck \
    && npm run build \
    && rm -rf node_modules "${HOME}/.npm"

FROM ${NGINX_IMAGE}

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/build/ /usr/share/nginx/html/docs/

USER 101:101
EXPOSE 8080
ENTRYPOINT ["nginx", "-g", "daemon off;"]
