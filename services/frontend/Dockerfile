# Build stage
FROM node:18-alpine AS builder
WORKDIR /app
COPY services/frontend/package*.json ./
RUN npm install
COPY services/frontend/ .
RUN npm run build

# Serve stage
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY services/frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
