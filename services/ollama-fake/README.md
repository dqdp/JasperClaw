# ollama-fake

Purpose:
Deterministic fake model runtime used for CI smoke and local runtime verification.

Start here:
- `app/main.py`: open first when changing the fake Ollama HTTP contract used by smoke.

Index:
- `app/`: open when changing fake runtime endpoints or in-memory request tracking.
- `tests/`: open when extending the fake runtime contract or debugging smoke regressions.
- `Dockerfile`: open when CI smoke image build or container startup changes.
- `requirements.txt`: open when the fake runtime needs additional Python dependencies.
