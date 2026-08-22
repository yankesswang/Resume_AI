# Frontend image — real production `vite build`, served by nginx.
#
# Build from the REPO ROOT so deploy/nginx/default.conf is inside the context:
#   docker build -f frontend/Dockerfile -t resume-ai-frontend:latest .
# (docker-compose.yml already sets context: . and this dockerfile path.)

# ---------- Stage 1: build the SPA ----------
FROM node:22-alpine AS builder

WORKDIR /build

# Lockfile first so `npm ci` is cached until dependencies actually change.
COPY frontend/package.json frontend/package-lock.json* ./

# npm ci needs a lockfile; fall back to install so a fresh checkout without one
# still builds rather than failing at image build time.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/ ./

RUN npm run build

# ---------- Stage 2: nginx ----------
FROM nginx:1.27-alpine AS runtime

# The stock config's default server would shadow ours.
RUN rm -f /etc/nginx/conf.d/default.conf

COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

# nginx:alpine already ships an unprivileged `nginx` user (uid 101). Give it
# ownership of the paths it writes so the master can run non-root; port 80 is
# fine unprivileged because modern nginx images bind via a non-root-capable
# setup and compose maps a high host port anyway.
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx \
    && touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid

USER nginx

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:80/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
