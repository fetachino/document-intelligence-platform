FROM node:18-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* /app/
RUN npm ci --silent
COPY frontend /app
RUN npm run build

FROM nginx:1.27-alpine
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
RUN sed -i 's#pid[[:space:]].*;#pid /tmp/nginx.pid;#' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /etc/nginx/conf.d /var/cache/nginx
ENV API_UPSTREAM=http://backend:8000
USER nginx
EXPOSE 3000
