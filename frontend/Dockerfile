FROM node:18-alpine
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* /app/
RUN npm ci --silent
COPY frontend /app
CMD ["npm", "run", "start"]
