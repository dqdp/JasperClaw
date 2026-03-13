FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip setuptools \
    && pip install --no-cache-dir -r requirements.txt
COPY app /app/app
RUN mkdir -p /app/voices \
    && python - <<'PY'
from pathlib import Path
import subprocess
import tomllib

registry = tomllib.loads(Path("/app/app/voices.toml").read_text())
voices = registry.get("voices")
if not isinstance(voices, dict) or not voices:
    raise SystemExit("voices.toml must declare at least one voice")

models = sorted(
    {
        entry["model"].strip()
        for entry in voices.values()
        if isinstance(entry, dict)
        and isinstance(entry.get("model"), str)
        and entry["model"].strip()
    }
)
if not models:
    raise SystemExit("voices.toml must declare at least one Piper model")

for model in models:
    subprocess.run(
        [
            "python",
            "-m",
            "piper.download_voices",
            "--download-dir",
            "/app/voices",
            model,
        ],
        check=True,
    )
PY
ENV PIPER_MODEL_DIR=/app/voices \
    PIPER_BINARY_PATH=piper \
    TTS_ENGINE=piper \
    TTS_VOICE_REGISTRY_PATH=/app/app/voices.toml
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
