"""Install, inspect or stop this project's macOS login service. No secrets in the plist."""

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
LABEL = "local.claude.verifydesk"
DOMAIN = f"gui/{os.getuid()}"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description="Управление ботом на macOS")
    parser.add_argument("action", choices=["install", "status", "restart", "stop"])
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Этот способ запуска предназначен для macOS. На сервере используйте Docker Compose.")
    target = f"{DOMAIN}/{LABEL}"
    if args.action == "install":
        python = ROOT / ".venv" / "bin" / "python"
        if not python.is_file() or not (ROOT / ".env").is_file():
            parser.error("Сначала установите зависимости в .venv и заполните .env.")
        data = ROOT / "data"
        data.mkdir(mode=0o700, exist_ok=True)
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": LABEL,
            "ProgramArguments": [str(python), "-m", "verifydesk"],
            "WorkingDirectory": str(ROOT),
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "ThrottleInterval": 20,
            "ProcessType": "Background",
            "StandardOutPath": str(data / "bot.log"),
            "StandardErrorPath": str(data / "bot.log"),
            "EnvironmentVariables": {"PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        }
        if PLIST.exists():
            existing = plistlib.loads(PLIST.read_bytes())
            if existing.get("WorkingDirectory") != str(ROOT):
                parser.error(
                    "Сервис с этим именем относится к другой папке. Сначала остановите прежний экземпляр."
                )
        launchctl("bootout", target)
        PLIST.write_bytes(plistlib.dumps(payload))
        PLIST.chmod(0o600)
        result = launchctl("bootstrap", DOMAIN, str(PLIST))
        # launchd can finish bootout shortly after returning; retry this known local race.
        for _ in range(3):
            if result.returncode == 0:
                break
            time.sleep(0.5)
            result = launchctl("bootstrap", DOMAIN, str(PLIST))
        if result.returncode:
            print("Не удалось подключить сервис macOS. Запустите бота через Запустить.command.")
            return 1
        print("Бот подключён как фоновый сервис macOS.")
    elif args.action == "stop":
        result = launchctl("bootout", target)
        if result.returncode and "Could not find service" not in result.stderr:
            print("Сервис не запущен или недоступен.")
            return 1
        print("Бот остановлен. Для запуска: manage_service.py install")
    elif args.action == "restart":
        result = launchctl("kickstart", "-k", target)
        if result.returncode:
            print("Сервис не подключён. Сначала выполните manage_service.py install.")
            return 1
        print("Запрошен перезапуск бота.")
    else:
        result = launchctl("print", target)
        if result.returncode:
            print("Сервис не подключён.")
            return 1
        for line in result.stdout.splitlines():
            if any(key in line for key in ("state =", "pid =", "last exit code =", "runs =")):
                print(line.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
