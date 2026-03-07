FROM mcr.microsoft.com/playwright:v1.49.0-noble

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm ci

# Copy source and build
COPY tsconfig.json ./
COPY src/ ./src/
RUN npm run build

# PulseAudio null sink for audio capture fallback
RUN apt-get update && apt-get install -y pulseaudio && rm -rf /var/lib/apt/lists/*

EXPOSE 3001

CMD ["node", "dist/index.js"]
