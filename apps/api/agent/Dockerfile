FROM node:22-bookworm-slim AS build

WORKDIR /app
COPY agent/package.json agent/package-lock.json ./
COPY agent/patches ./patches
RUN npm ci --ignore-scripts
RUN ./node_modules/.bin/patch-package
COPY agent/src ./src
COPY agent/skills ./skills
COPY agent/scripts/verify-skills.ts ./scripts/verify-skills.ts
COPY agent/tsconfig.json ./
RUN npm run verify:skills
RUN npm run build
RUN npm prune --omit=dev

FROM node:22-bookworm-slim
WORKDIR /app
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/skills ./skills
ENV AGENT_RUNTIME_HOST=0.0.0.0 NODE_ENV=production
EXPOSE 8765
CMD ["node", "dist/main.js"]
