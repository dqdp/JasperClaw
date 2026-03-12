# Agent API Core

Purpose:
This directory contains service-wide infrastructure for auth, config, logging, and error handling.

Start here:
- `config.py`: open first when a change introduces or consumes configuration.

Index:
- `auth.py`: open when changing internal bearer authentication behavior.
- `config.py`: open when changing settings, defaults, or config parsing.
- `errors.py`: open when changing API error envelopes or request-id helpers.
- `logging.py`: open when changing structured log event formatting.
