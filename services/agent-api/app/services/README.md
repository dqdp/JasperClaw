# Agent API Services

Purpose:
This directory contains orchestration logic that sits above transport and below persistence/providers.

Start here:
- `chat.py`: open first for the main chat, retrieval, and tools orchestration path.

Index:
- `chat.py`: open when changing runtime prompt assembly, tool policy, persistence flow, or streaming orchestration.
- `readiness.py`: open when changing downstream dependency checks behind `/readyz`.
