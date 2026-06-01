# Stage 0, "build-stage", based on Bun, to build and compile the frontend.
FROM oven/bun:1-alpine AS build-stage

WORKDIR /app

COPY package.json bun.lock /app/

COPY frontend/package.json /app/frontend/

WORKDIR /app/frontend

RUN bun install

COPY ./frontend /app/frontend

# VITE_API_URL must be exported as an environment variable — not left as a
# bare ARG — so that Vite actually picks it up during `bun run build`. An ARG
# alone is invisible to the build process, which would silently bake in the
# fallback (localhost) URL and break the deployed frontend.
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

RUN bun run build


# Stage 1, based on the unprivileged Nginx image, to serve only the compiled
# app. nginx-unprivileged runs as a non-root user and listens on port 8080,
# which limits the blast radius of a container compromise.
FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY --from=build-stage /app/frontend/dist/ /usr/share/nginx/html

COPY ./frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY ./frontend/nginx-backend-not-found.conf /etc/nginx/extra-conf.d/backend-not-found.conf
