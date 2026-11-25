FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /bin/
WORKDIR /app
ADD . .
RUN HOME=/tmp uv sync --no-cache --locked --no-dev --link-mode copy
ENV PRODUCTION_MODE=true HOST=0.0.0.0 PORT=8000
CMD ["/app/.venv/bin/server"]
