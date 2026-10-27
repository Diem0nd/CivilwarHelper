import os
import subprocess
import sys
from pathlib import Path

from civilwarhelper.app import bot

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_COMMANDS = sorted([
    "ping", "register", "lolprofile", "valprofile", "refreshlol", "refreshval",
    "create-inhouse", "unregister", "inhouse-transfer",
    "inhouse-list", "end-inhouse",
    "userprofile", "resetstats", "rps", "dice",
])


def test_all_slash_commands_are_registered():
    assert sorted(command.name for command in bot.tree.get_commands()) == EXPECTED_COMMANDS


def test_error_handler_is_installed():
    assert bot.tree.on_error.__name__ == "on_app_command_error"


def test_app_imports_without_token_or_network():
    env = {k: v for k, v in os.environ.items() if k != "DISCORD_TOKEN"}
    env["DISCORD_TOKEN"] = ""
    result = subprocess.run(
        [sys.executable, "-c", "import civilwarhelper.app"],
        cwd=ROOT,
        env={**env, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
