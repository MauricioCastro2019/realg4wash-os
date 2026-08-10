# wsgi.py — Mi Auto Pro preview
#
# Esta rama de preview no necesita base de datos: /garage usa un dataset
# sanitizado en memoria. No ejecutamos migraciones al arrancar porque los
# PR Environments enfocados de Railway no despliegan Postgres si el PR no
# modifica ese servicio. Producción conserva su comportamiento actual.

from app import create_app

app = create_app()
