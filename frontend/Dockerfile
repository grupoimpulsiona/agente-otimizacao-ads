# Stage 1 — build React
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
# As variáveis VITE_ são passadas como build args
ARG VITE_API_URL=http://31.97.170.137:8000
ARG VITE_API_KEY=impulsiona-agente-ads-2026-seguro
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_API_KEY=$VITE_API_KEY
RUN npm run build

# Stage 2 — serve com Nginx
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
