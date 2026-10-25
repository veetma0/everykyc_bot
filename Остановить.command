#!/bin/zsh
set -e
cd -- "${0:A:h}"
exec .venv/bin/python manage_service.py stop
