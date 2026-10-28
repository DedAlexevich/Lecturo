FROM node:26-alpine AS build
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
ARG VITE_TELEGRAM_BOT_USERNAME
ENV VITE_TELEGRAM_BOT_USERNAME=$VITE_TELEGRAM_BOT_USERNAME
RUN npm run build

FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
