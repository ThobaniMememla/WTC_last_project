
FROM node:14-alpine


WORKDIR /app


COPY package*.json ./


RUN npm cache clean --force \
    && npm install --no-optional --prefer-offline

COPY . .


RUN npm run build


RUN npm install -g serve


EXPOSE 3000


CMD ["serve", "-s", "build"]
