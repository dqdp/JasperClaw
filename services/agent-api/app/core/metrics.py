from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from threading import Lock


class _CounterMetric:
    def __init__(self, name: str, description: str, label_names: tuple[str, ...]) -> None:
        self._name = name
        self._description = description
        self._label_names = label_names
        self._values: dict[tuple[str, ...], int] = defaultdict(int)
        self._lock = Lock()

    def inc(self, **labels: str) -> None:
        key = tuple(labels[name] for name in self._label_names)
        with self._lock:
            self._values[key] += 1

    def reset(self) -> None:
        with self._lock:
            self._values.clear()

    def render_prometheus(self) -> list[str]:
        lines = [
            f"# HELP {self._name} {self._description}",
            f"# TYPE {self._name} counter",
        ]
        with self._lock:
            items = sorted(self._values.items())
        for key, value in items:
            if self._label_names:
                rendered_labels = ",".join(
                    f'{name}="{_escape_label(label)}"'
                    for name, label in zip(self._label_names, key, strict=True)
                )
                lines.append(f"{self._name}{{{rendered_labels}}} {value}")
            else:
                lines.append(f"{self._name} {value}")
        return lines


class _HistogramMetric:
    def __init__(
        self,
        name: str,
        description: str,
        label_names: tuple[str, ...],
        buckets: tuple[float, ...],
    ) -> None:
        self._name = name
        self._description = description
        self._label_names = label_names
        self._buckets = tuple(sorted(buckets))
        self._counts: dict[tuple[str, ...], list[int]] = defaultdict(
            lambda: [0] * (len(self._buckets) + 1)
        )
        self._sums: dict[tuple[str, ...], float] = defaultdict(float)
        self._observations: dict[tuple[str, ...], int] = defaultdict(int)
        self._lock = Lock()

    def observe(self, value: float, **labels: str) -> None:
        key = tuple(labels[name] for name in self._label_names)
        bucket_index = bisect_left(self._buckets, value)
        with self._lock:
            self._counts[key][bucket_index] += 1
            self._sums[key] += value
            self._observations[key] += 1

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._sums.clear()
            self._observations.clear()

    def render_prometheus(self) -> list[str]:
        lines = [
            f"# HELP {self._name} {self._description}",
            f"# TYPE {self._name} histogram",
        ]
        with self._lock:
            keys = sorted(self._observations.keys())
            counts = {key: list(self._counts[key]) for key in keys}
            sums = {key: self._sums[key] for key in keys}
            observations = {key: self._observations[key] for key in keys}
        for key in keys:
            cumulative = 0
            for boundary, count in zip(self._buckets, counts[key][:-1], strict=True):
                cumulative += count
                lines.append(
                    f"{self._name}_bucket{self._render_labels(key, extra=('le', _format_bucket(boundary)))} {cumulative}"
                )
            cumulative += counts[key][-1]
            lines.append(
                f"{self._name}_bucket{self._render_labels(key, extra=('le', '+Inf'))} {cumulative}"
            )
            lines.append(f"{self._name}_sum{self._render_labels(key)} {sums[key]}")
            lines.append(f"{self._name}_count{self._render_labels(key)} {observations[key]}")
        return lines

    def _render_labels(
        self,
        key: tuple[str, ...],
        *,
        extra: tuple[str, str] | None = None,
    ) -> str:
        labels = [
            (name, label)
            for name, label in zip(self._label_names, key, strict=True)
        ]
        if extra is not None:
            labels.append(extra)
        if not labels:
            return ""
        rendered = ",".join(
            f'{name}="{_escape_label(value)}"' for name, value in labels
        )
        return f"{{{rendered}}}"


class AgentApiMetrics:
    def __init__(self) -> None:
        self._request_total = _CounterMetric(
            "agent_api_http_request_total",
            "HTTP requests handled by agent-api.",
            ("method", "path_group", "status_class"),
        )
        self._request_duration = _HistogramMetric(
            "agent_api_http_request_duration_seconds",
            "HTTP request duration in seconds.",
            ("method", "path_group"),
            (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        )
        self._chat_runtime_total = _CounterMetric(
            "agent_api_chat_runtime_total",
            "Chat runtime outcomes emitted by agent-api.",
            ("outcome", "phase", "public_model"),
        )
        self._chat_runtime_duration = _HistogramMetric(
            "agent_api_chat_runtime_duration_seconds",
            "Chat runtime duration in seconds.",
            ("outcome", "phase", "public_model"),
            (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
        )
        self._chat_storage_total = _CounterMetric(
            "agent_api_chat_storage_total",
            "Chat persistence outcomes.",
            ("outcome",),
        )
        self._tool_execution_total = _CounterMetric(
            "agent_api_tool_execution_total",
            "Tool execution outcomes emitted by agent-api.",
            ("error_type", "outcome", "tool_name"),
        )
        self._tool_audit_total = _CounterMetric(
            "agent_api_tool_audit_total",
            "Tool audit persistence outcomes.",
            ("outcome",),
        )
        self._readiness_total = _CounterMetric(
            "agent_api_readiness_total",
            "Readiness check outcomes.",
            ("status",),
        )

    def record_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        method_label = method.upper()
        path_group = _classify_path(path)
        self._request_total.inc(
            method=method_label,
            path_group=path_group,
            status_class=_status_class(status_code),
        )
        self._request_duration.observe(
            duration_seconds,
            method=method_label,
            path_group=path_group,
        )

    def record_chat_runtime(
        self,
        *,
        outcome: str,
        phase: str,
        public_model: str,
        duration_seconds: float,
    ) -> None:
        self._chat_runtime_total.inc(
            outcome=outcome,
            phase=phase,
            public_model=public_model,
        )
        self._chat_runtime_duration.observe(
            duration_seconds,
            outcome=outcome,
            phase=phase,
            public_model=public_model,
        )

    def record_chat_storage(self, *, outcome: str) -> None:
        self._chat_storage_total.inc(outcome=outcome)

    def record_tool_execution(
        self,
        *,
        tool_name: str,
        outcome: str,
        error_type: str | None,
    ) -> None:
        self._tool_execution_total.inc(
            error_type=(error_type or "none"),
            outcome=outcome,
            tool_name=tool_name,
        )

    def record_tool_audit(self, *, outcome: str) -> None:
        self._tool_audit_total.inc(outcome=outcome)

    def record_readiness(self, *, status: str) -> None:
        self._readiness_total.inc(status=status)

    def reset(self) -> None:
        for metric in (
            self._request_total,
            self._request_duration,
            self._chat_runtime_total,
            self._chat_runtime_duration,
            self._chat_storage_total,
            self._tool_execution_total,
            self._tool_audit_total,
            self._readiness_total,
        ):
            metric.reset()

    def render_prometheus(self) -> str:
        lines: list[str] = []
        for metric in (
            self._request_total,
            self._request_duration,
            self._chat_runtime_total,
            self._chat_runtime_duration,
            self._chat_storage_total,
            self._tool_execution_total,
            self._tool_audit_total,
            self._readiness_total,
        ):
            lines.extend(metric.render_prometheus())
        return "\n".join(lines) + "\n"


_AGENT_API_METRICS = AgentApiMetrics()


def get_agent_metrics() -> AgentApiMetrics:
    return _AGENT_API_METRICS


def _classify_path(path: str) -> str:
    if path == "/healthz":
        return "healthz"
    if path == "/readyz":
        return "readyz"
    if path == "/metrics":
        return "metrics"
    if path == "/v1/chat/completions":
        return "chat_completions"
    if path == "/v1/models":
        return "models"
    if path == "/v1/audio/transcriptions":
        return "audio_transcriptions"
    if path == "/v1/audio/speech":
        return "audio_speech"
    return "other"


def _status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


def _format_bucket(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
