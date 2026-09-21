# Build the React app, then serve it and the API from one Python image (render.yaml, Cloud Run).
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
# Empty VITE_API: the page calls /api on its own origin, which FastAPI serves.
RUN VITE_API= npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=web /web/dist web/dist
# The host sets $PORT. Replay needs no keys; set VISEXP_PUBLIC_DEMO=1 for a public link.
CMD ["sh", "-c", "python -m uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
