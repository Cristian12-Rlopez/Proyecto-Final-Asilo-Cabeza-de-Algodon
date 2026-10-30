#!/usr/bin/env bash
# Script de construcción para Render. Se ejecuta en cada despliegue.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Crea el usuario administrador la primera vez (usa las variables DJANGO_SUPERUSER_*; si ya existe, lo omite)
if [[ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]]; then
  python manage.py createsuperuser --no-input || true
fi
