from __future__ import annotations

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


class AlertDeliveryMetrics:
    def __init__(self) -> None:
        self._claim_total = _CounterMetric(
            "telegram_alert_delivery_claim_total",
            "Alert deliveries claimed for processing.",
            ("origin",),
        )
        self._claim_skipped_total = _CounterMetric(
            "telegram_alert_delivery_claim_skipped_total",
            "Alert deliveries skipped because they were no longer claimable.",
            (),
        )
        self._target_attempt_total = _CounterMetric(
            "telegram_alert_delivery_target_attempt_total",
            "Durably recorded target delivery attempts.",
            ("error_class", "status"),
        )
        self._target_attempt_persist_failed_total = _CounterMetric(
            "telegram_alert_delivery_target_attempt_persist_failed_total",
            "Target attempt persistence failures.",
            (),
        )
        self._finalize_total = _CounterMetric(
            "telegram_alert_delivery_finalize_total",
            "Finalized alert deliveries by status.",
            ("status",),
        )
        self._finalize_failed_total = _CounterMetric(
            "telegram_alert_delivery_finalize_failed_total",
            "Alert delivery finalize failures.",
            (),
        )

    def record_claim(self, *, origin: str) -> None:
        self._claim_total.inc(origin=origin)

    def record_claim_skipped(self) -> None:
        self._claim_skipped_total.inc()

    def record_target_attempt(self, *, status: str, error_code: str | None) -> None:
        self._target_attempt_total.inc(
            error_class=_classify_error_code(error_code),
            status=status,
        )

    def record_target_attempt_persist_failed(self) -> None:
        self._target_attempt_persist_failed_total.inc()

    def record_finalize(self, *, status: str) -> None:
        self._finalize_total.inc(status=status)

    def record_finalize_failed(self) -> None:
        self._finalize_failed_total.inc()

    def render_prometheus(self) -> str:
        lines: list[str] = []
        for metric in (
            self._claim_total,
            self._claim_skipped_total,
            self._target_attempt_total,
            self._target_attempt_persist_failed_total,
            self._finalize_total,
            self._finalize_failed_total,
        ):
            lines.extend(metric.render_prometheus())
        return "\n".join(lines) + "\n"


def _classify_error_code(error_code: str | None) -> str:
    if error_code is None:
        return "none"
    if error_code == "http_429":
        return "http_429"
    if error_code.startswith("http_4"):
        return "http_4xx"
    if error_code.startswith("http_5"):
        return "http_5xx"
    return "other"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
