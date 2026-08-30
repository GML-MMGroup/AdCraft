FROM node:22-bookworm-slim AS build

WORKDIR /app
COPY agent/package.json agent/package-lock.json ./
COPY agent/patches ./patches
RUN npm ci --ignore-scripts && npx patch-package
COPY agent/src ./src
COPY agent/src/generated ./src/generated
COPY agent/skills ./skills
COPY agent/scripts ./scripts
COPY agent/tsconfig.json ./
RUN npm run verify:skills
RUN npm run build
RUN mkdir -p dist/src/generated && cp src/generated/*.json dist/src/generated/
RUN npm prune --omit=dev

FROM node:22-bookworm-slim
WORKDIR /app
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/skills ./skills
COPY --from=build /app/skills ./dist/skills
ENV AGENT_RUNTIME_HOST=0.0.0.0 NODE_ENV=production
EXPOSE 8765
CMD ["node", "dist/src/main.js"]
