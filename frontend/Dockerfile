# Shared dependency install
FROM node:20-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci || npm install

# Test stage: typecheck + unit tests (build with `--target test`)
FROM deps AS test

COPY . .
RUN npm run typecheck && npm test

# Build stage
FROM deps AS build

COPY . .
RUN npm run build

# Serve stage
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
