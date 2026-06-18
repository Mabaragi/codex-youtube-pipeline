FROM node:22-alpine AS deps

WORKDIR /repo

ENV CI=true

RUN corepack enable

COPY pnpm-lock.yaml pnpm-workspace.yaml ./
COPY ops-ui/package.json ./ops-ui/package.json
RUN pnpm install --filter codex-sdk-ops-ui --frozen-lockfile

FROM node:22-alpine AS builder

WORKDIR /repo

ENV CI=true
ENV NEXT_TELEMETRY_DISABLED=1

RUN corepack enable

COPY --from=deps /repo/pnpm-lock.yaml ./pnpm-lock.yaml
COPY --from=deps /repo/pnpm-workspace.yaml ./pnpm-workspace.yaml
COPY --from=deps /repo/node_modules ./node_modules
COPY --from=deps /repo/ops-ui/node_modules ./ops-ui/node_modules
COPY ops-ui ./ops-ui
WORKDIR /repo/ops-ui
RUN ./node_modules/.bin/next build

FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=builder /repo/ops-ui/public ./ops-ui/public
COPY --from=builder --chown=nextjs:nodejs /repo/ops-ui/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /repo/ops-ui/.next/static ./ops-ui/.next/static

USER nextjs

WORKDIR /app/ops-ui

EXPOSE 3000

CMD ["node", "server.js"]
