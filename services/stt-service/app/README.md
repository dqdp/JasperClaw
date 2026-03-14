# STT Service App

Purpose:
This directory contains the FastAPI speech-to-text service, the internal engine
boundary, and the transcription facade.

Start here:
- `main.py`: open when changing the HTTP contract.

Index:
- `core/`: open when changing configuration or error behavior.
- `engines/`: open when changing the runtime integration layer.
- `services/`: open when changing transcription policy or concurrency behavior.
- `schemas.py`: open when changing request/response payloads.
