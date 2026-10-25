#!/bin/zsh
set -e
cd -- "${0:A:h}"
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  open -e .env
  print 'Заполните BOT_TOKEN и ADMIN_IDS в открывшемся файле, сохраните его и запустите ещё раз.'
  read -r '?Нажмите Enter, чтобы закрыть окно.'
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python -m verifydesk
