# Multi-stage build: compile the Vite/React app, then serve the static
# dist/ output with nginx. VITE_API_URL/VITE_API_KEY are baked into the JS
# bundle at build time (Vite env vars always are -- see dashboard/README.md),
# so they're passed as build args, not runtime env.
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=http://localhost:8000
ARG VITE_API_KEY=dev-reviewer-key
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_API_KEY=${VITE_API_KEY}
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
