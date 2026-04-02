FROM mcr.microsoft.com/playwright:v1.49.0-noble

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm ci

# Copy source and build
COPY tsconfig.json ./
COPY src/ ./src/
RUN npm run build

# Install Xvfb, PulseAudio, and Google Chrome for headed mode with virtual display and audio
RUN apt-get update && \
    apt-get install -y xvfb pulseaudio && \
    rm -rf /var/lib/apt/lists/* && \
    npx playwright install --with-deps chrome

# Set display environment variable for Xvfb
ENV DISPLAY=:99
ENV XDG_RUNTIME_DIR=/tmp/runtime-pwuser

# Prepare PulseAudio directories and config for non-root user (pwuser)
RUN mkdir -p /home/pwuser/.config/pulse /tmp/runtime-pwuser && \
    echo "default-server = unix:/tmp/pulseaudio.socket" > /home/pwuser/.config/pulse/client.conf && \
    chown -R pwuser:pwuser /home/pwuser/.config /tmp/runtime-pwuser

# Copy entrypoint script and fix Windows line endings
COPY entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Run as non-root user (pwuser exists in the playwright base image)
USER pwuser

EXPOSE 3001

ENTRYPOINT ["/app/entrypoint.sh"]
