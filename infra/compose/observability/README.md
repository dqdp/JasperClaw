# Observability Stack

Purpose:
This directory contains the runnable Prometheus and Grafana configuration used by the optional observability profile.

Start here:
- `prometheus/prometheus.yml`: open first when changing scrape targets or rule loading.

Index:
- `prometheus/`: scrape config and alert rules for currently instrumented services.
- `grafana/`: provisioned datasource and dashboard configuration.

Run:
- `docker compose -f infra/compose/compose.yml --profile observability up -d postgres ollama agent-api telegram-ingress prometheus grafana`

Access:
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- Grafana credentials: `admin` / `admin`

Smoke check:
- `docker compose -f infra/compose/compose.yml --profile observability up -d postgres ollama agent-api telegram-ingress prometheus grafana && curl -fsS http://localhost:9090/api/v1/targets | jq -e '.data.activeTargets | map(select(.labels.job == \"agent-api\" or .labels.job == \"telegram-ingress\") | .health == \"up\") | length == 2' && curl -fsS http://localhost:3000/api/health`

Notes:
- this stack is intentionally minimal and currently covers `agent-api` and `telegram-ingress`
- it is activated only through the Compose `observability` profile
- it relies on the existing `/metrics` endpoints exported by those two services
