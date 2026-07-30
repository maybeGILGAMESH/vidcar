FROM node:20.18.1-bookworm-slim AS deps
WORKDIR /repo
COPY packages/api-client /repo/packages/api-client
WORKDIR /repo/packages/api-client
RUN npm install && npm run build
WORKDIR /repo/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm install --no-audit --no-fund

FROM node:20.18.1-bookworm-slim AS build
WORKDIR /repo
COPY --from=deps /repo/packages/api-client /repo/packages/api-client
COPY --from=deps /repo/apps/web/node_modules /repo/apps/web/node_modules
COPY apps/web/package.json apps/web/package-lock.json apps/web/tsconfig.json apps/web/next.config.mjs apps/web/next-env.d.ts /repo/apps/web/
COPY apps/web/app /repo/apps/web/app
COPY apps/web/lib /repo/apps/web/lib
COPY apps/web/public /repo/apps/web/public
WORKDIR /repo/apps/web
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20.18.1-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000
COPY --from=build /repo/apps/web/.next ./.next
COPY --from=build /repo/apps/web/node_modules ./node_modules
COPY --from=build /repo/apps/web/package.json ./package.json
COPY --from=build /repo/apps/web/public ./public
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["npm", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]
