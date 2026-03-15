# Ops

Purpose:
This directory defines operational policy, configuration ownership, observability expectations, and stable failure semantics.

Start here:
- `configuration.md`: open first when adding or changing environment variables.

Index:
- `agent-action-policy.md`: open when a feature touches tool risk classes, approvals, or sandbox requirements.
- `configuration.md`: open when changing config shape, defaults, or service-level ownership.
- `dashboard-and-alert-rollout.md`: open when defining the first Grafana panels or alert rules for implemented service metrics.
- `demo-household-config.md`: open when defining the explicit demo-only household config path that can make Telegram household capabilities `demo` instead of `unconfigured`.
- `error-semantics.md`: open when mapping internal failures to explicit client-facing errors.
- `household-config.md`: open when changing the single-household trusted-chat and alias configuration contract for the default baseline.
- `observability.md`: open when changing logs, health checks, readiness, or tracing expectations.
- `version-policy.md`: open when changing pinned runtime versions, image tags, or upgrade expectations.
