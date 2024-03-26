#!/bin/sh
cd src

python manage.py migrate --no-input
python manage.py collectstatic --no-input
python 01_script_base.py

# Para correr en modo wsgi
# chmod -R 755 /app/static/
# chmod -R 755 /app/media/
# gunicorn config.wsgi:application --bind 0.0.0.0:8000

python manage.py runserver 0.0.0.0:8000