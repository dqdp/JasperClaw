from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE_SCRIPT = REPO_ROOT / "infra" / "scripts" / "smoke-telegram-ingress.py"


def test_smoke_telegram_ingress_covers_household_alias_and_trust_paths() -> None:
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert "TELEGRAM_SMOKE_CHECK_HOUSEHOLD" in script
    assert "TELEGRAM_SMOKE_TRUSTED_CHAT_ID" in script
    assert "TELEGRAM_SMOKE_ALIAS" in script
    assert '"/aliases"' in script
    assert '"/send ' in script
    assert "not authorized for household assistant access" in script
