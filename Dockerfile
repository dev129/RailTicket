FROM python:3.13-slim

WORKDIR /app

# Dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App
COPY railengine ./railengine

EXPOSE 8000
ENV PORT=8000

# Provider is auto-selected: set RAIL_API_BASE + RAIL_API_KEY for live mode,
# otherwise the offline MockProvider is used.
CMD ["sh", "-c", "uvicorn railengine.api:app --host 0.0.0.0 --port ${PORT}"]
