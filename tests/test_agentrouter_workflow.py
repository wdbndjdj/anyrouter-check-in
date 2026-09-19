import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "agentrouter.yml"


def _validator_script() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    start_marker = "          python - <<'PY'\n"
    end_marker = "\n          PY"
    start = workflow.index(start_marker) + len(start_marker)
    end = workflow.index(end_marker, start)
    return textwrap.dedent(workflow[start:end])


def _account(index: int, email: str | None = None) -> dict[str, str]:
    return {
        "name": f"agentrouter-{index:02d}",
        "provider": "agentrouter",
        "email": email or f"account-{index}@example.test",
        "password": f"password-{index}",
    }


def _run_validator(tmp_path: Path, next_email: str | None = "account-23@example.test"):
    groups = {
        "ANYROUTER_ACCOUNTS_BASE": [_account(index) for index in range(1, 9)],
        "ANYROUTER_ACCOUNTS_EXTRA": [_account(index) for index in range(9, 13)],
        "ANYROUTER_ACCOUNTS_ADDED": [_account(index) for index in range(13, 18)],
        "ANYROUTER_ACCOUNTS_MORE": [_account(index) for index in range(18, 22)],
        "ANYROUTER_ACCOUNTS_SINGLE": [_account(22)],
    }
    if next_email is not None:
        groups["ANYROUTER_ACCOUNTS_NEXT"] = [_account(23, next_email)]

    env = os.environ.copy()
    env.update({name: json.dumps(value) for name, value in groups.items()})
    accounts_file = tmp_path / "agentrouter-accounts.json"
    env["AGENTROUTER_ACCOUNTS_FILE"] = str(accounts_file)
    result = subprocess.run(
        [sys.executable, "-c", _validator_script()],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    accounts = json.loads(accounts_file.read_text(encoding="utf-8"))
    return result, accounts


def test_duplicate_next_email_is_removed_from_runtime_accounts(tmp_path):
    result, accounts = _run_validator(tmp_path, "account-1@example.test")

    assert result.returncode == 0, result.stderr
    assert "WARNING: duplicate next account email; skipping agentrouter-23" in result.stdout
    assert len(accounts) == 22
    assert [account["name"] for account in accounts] == [
        f"agentrouter-{index:02d}" for index in range(1, 23)
    ]


def test_unique_next_email_is_kept(tmp_path):
    result, accounts = _run_validator(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Validated AgentRouter accounts: count=23" in result.stdout
    assert len(accounts) == 23
    assert accounts[-1]["name"] == "agentrouter-23"


def test_missing_next_secret_keeps_existing_accounts(tmp_path):
    result, accounts = _run_validator(tmp_path, None)

    assert result.returncode == 0, result.stderr
    assert len(accounts) == 22
