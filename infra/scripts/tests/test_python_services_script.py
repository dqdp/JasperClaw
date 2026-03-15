from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_SCRIPT = REPO_ROOT / "infra" / "scripts" / "test-python-services.sh"


def _write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_python_service_runner_exports_repo_root_on_pythonpath(tmp_path: Path) -> None:
    log_path = tmp_path / "python.log"
    python_stub = tmp_path / "python-stub.sh"
    _write_file(
        python_stub,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'printf "%s\\n" "${{PWD}}|${{PYTHONPATH:-}}" >> "{log_path}"',
                "exit 0",
                "",
            ]
        ),
    )

    env = os.environ.copy()
    env["PYTHON_BIN"] = str(python_stub)

    result = subprocess.run(
        ["bash", str(TEST_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    calls = log_path.read_text(encoding="utf-8").splitlines()
    assert calls, "expected the runner to invoke the Python stub"
    assert all(
        path_segment.startswith(str(REPO_ROOT))
        for path_segment in (line.split("|", 1)[1].split(":")[0] for line in calls)
    )
