FROM node:20-alpine AS build
WORKDIR /app
# Render пробрасывает env-переменные в сборку как build-args.
# NEXT_PUBLIC_* в Next.js вшиваются в бандл именно на этапе build.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm install
COPY apps/web/ ./
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "start"]
