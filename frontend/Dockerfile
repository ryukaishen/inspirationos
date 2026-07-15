# Dev image. Compose bind-mounts ./frontend over /app (with an anonymous
# volume shielding /app/node_modules). Production multi-stage images arrive
# with Milestone 9.
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]
