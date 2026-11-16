# Marswalk Planner on a Hugging Face Space (Docker SDK). push_space.py copies this file to the Space's root together
# with the committed code. The Space serves the FastAPI app on port 7860 (app_port in the Space card).
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

# Spaces run the container as user 1000; the app writes area cubes, tile caches and downloads next to the code.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 \
    CLAUDE_MODEL=claude-haiku-5-5 CLAUDE_EFFORT=medium AI_PARALLEL=8
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .

# ANTHROPIC_API_KEY comes from the Space's secrets (Settings -> Variables and secrets), never from this image.
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--timeout-graceful-shutdown", "5"]
