from typer.testing import CliRunner

import app.cli as cli_module
from app.cli import cli


def test_bootstrap_admin_is_a_named_cli_command() -> None:
    result = CliRunner().invoke(cli, ["bootstrap-admin", "--help"])

    assert result.exit_code == 0
    assert "Create the first administrator" in result.stdout
    assert "--email" in result.stdout
    assert "--password" in result.stdout


def test_bootstrap_and_engine_disposal_share_one_command_lifecycle(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    async def fake_bootstrap(email: str, password: str) -> None:
        calls.append((email, password))

    async def fake_dispose() -> None:
        calls.append(("disposed", None))

    monkeypatch.setattr(cli_module, "_bootstrap_admin", fake_bootstrap)
    monkeypatch.setattr(cli_module, "dispose_engine", fake_dispose)

    result = CliRunner().invoke(
        cli,
        [
            "bootstrap-admin",
            "--email",
            "admin@example.test",
            "--password",
            "a-long-test-password",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        ("admin@example.test", "a-long-test-password"),
        ("disposed", None),
    ]
