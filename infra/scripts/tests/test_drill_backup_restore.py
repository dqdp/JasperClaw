from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DRILL_SCRIPT = REPO_ROOT / "infra" / "scripts" / "drill-backup-restore.sh"


def _write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _docker_stub(path: Path, log_path: Path, env_paths_log: Path, captured_env: Path) -> Path:
    _write_file(
        path,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'printf "%s\\n" "$*" >> "{log_path}"',
                'if [[ "${1:-}" == "compose" ]]; then',
                '  env_file=""',
                '  prev=""',
                '  for arg in "$@"; do',
                '    if [[ "$prev" == "--env-file" ]]; then',
                '      env_file="$arg"',
                "      break",
                "    fi",
                '    prev="$arg"',
                "  done",
                '  if [[ -n "$env_file" ]]; then',
                f'    printf "%s\\n" "$env_file" >> "{env_paths_log}"',
                f'    cp "$env_file" "{captured_env}"',
                "  fi",
                '  case "$*" in',
                '    *" ps -q postgres"*)',
                f'      if grep -q " up -d postgres" "{log_path}" 2>/dev/null; then',
                '        printf "backup-postgres-1\\n"',
                "      fi",
                "      exit 0",
                "      ;;",
                '    *" up -d postgres"*) exit 0 ;;',
                '    *" run --rm --no-deps "*) exit 0 ;;',
                '    *" exec -T postgres pg_dump "*) printf "fake-pg-dump"; exit 0 ;;',
                '    *" exec -T postgres pg_restore "*) cat >/dev/null || true; exit 0 ;;',
                '    *"SELECT to_regclass(\'schema_migrations\');"*) printf "schema_migrations\\n"; exit 0 ;;',
                '    *"SELECT COUNT(*) FROM conversations WHERE id = \'conv_restore_seed\';"*) printf "1\\n"; exit 0 ;;',
                '    *"SELECT COUNT(*) FROM messages WHERE id = \'msg_restore_seed\';"*) printf "1\\n"; exit 0 ;;',
                '    *"SELECT COUNT(*) FROM conversations;"*) printf "1\\n"; exit 0 ;;',
                '    *" stop postgres"*) exit 0 ;;',
                "  esac",
                '  cat >/dev/null || true',
                "  exit 0",
                "fi",
                'if [[ "${1:-}" == "inspect" ]]; then',
                '  printf "healthy\\n"',
                "  exit 0",
                "fi",
                'if [[ "${1:-}" == "run" ]]; then',
                "  exit 0",
                "fi",
                "exit 0",
                "",
            ]
        ),
    )
    return path


def _run_drill(
    tmp_path: Path,
    *,
    root_env_file: Path,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path]:
    docker_log = tmp_path / "docker.log"
    env_paths_log = tmp_path / "env-paths.log"
    captured_env = tmp_path / "captured-compose.env"
    docker_stub = _docker_stub(
        tmp_path / "docker-stub.sh",
        docker_log,
        env_paths_log,
        captured_env,
    )

    env = os.environ.copy()
    env.update(
        {
            "ROOT_ENV_FILE": str(root_env_file),
            "ARTIFACT_DIR": str(tmp_path / "artifacts"),
            "PATH": f"{tmp_path}:{env['PATH']}",
        }
    )
    (tmp_path / "docker").symlink_to(docker_stub)

    result = subprocess.run(
        ["bash", str(DRILL_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, docker_log, env_paths_log, captured_env


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_drill_uses_effective_env_file_when_root_env_is_missing(tmp_path: Path) -> None:
    missing_env_file = tmp_path / "missing.env"

    result, docker_log, env_paths_log, captured_env = _run_drill(
        tmp_path,
        root_env_file=missing_env_file,
    )

    assert result.returncode == 0, result.stderr
    assert "Backup/restore drill succeeded" in result.stdout

    env_paths = env_paths_log.read_text(encoding="utf-8").splitlines()
    assert env_paths
    assert all(Path(path).exists() for path in env_paths)
    assert str(missing_env_file) not in env_paths

    effective_env = _parse_env_file(captured_env)
    assert effective_env["APP_VERSION"] == "dev"
    assert effective_env["GHCR_OWNER"] == "local"
    assert effective_env["POSTGRES_PASSWORD"] == "change-me"
    assert effective_env["INTERNAL_OPENAI_API_KEY"] == "test-internal-key"
    assert effective_env["WEBUI_SECRET_KEY"] == "test-webui-secret"
    assert effective_env["DOMAIN"] == "localhost"

    docker_calls = docker_log.read_text(encoding="utf-8")
    assert "--env-file" in docker_calls


def test_drill_materializes_root_env_values_into_effective_env_file(tmp_path: Path) -> None:
    root_env_file = tmp_path / "backup.env"
    root_env_file.write_text(
        "\n".join(
            [
                "APP_VERSION=release-42",
                "GHCR_OWNER=acme",
                "POSTGRES_PASSWORD=super-secret",
                "INTERNAL_OPENAI_API_KEY=internal-42",
                "WEBUI_SECRET_KEY=webui-42",
                "DOMAIN=backup.example.test",
                "TTS_DEFAULT_VOICE=assistant-fast",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result, _docker_log, env_paths_log, captured_env = _run_drill(
        tmp_path,
        root_env_file=root_env_file,
    )

    assert result.returncode == 0, result.stderr

    env_paths = env_paths_log.read_text(encoding="utf-8").splitlines()
    assert env_paths
    assert str(root_env_file) not in env_paths

    effective_env = _parse_env_file(captured_env)
    assert effective_env["APP_VERSION"] == "release-42"
    assert effective_env["GHCR_OWNER"] == "acme"
    assert effective_env["POSTGRES_PASSWORD"] == "super-secret"
    assert effective_env["INTERNAL_OPENAI_API_KEY"] == "internal-42"
    assert effective_env["WEBUI_SECRET_KEY"] == "webui-42"
    assert effective_env["DOMAIN"] == "backup.example.test"
    assert effective_env["TTS_DEFAULT_VOICE"] == "assistant-fast"
