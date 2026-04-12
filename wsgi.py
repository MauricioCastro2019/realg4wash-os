# wsgi.py
from app import create_app
from flask_migrate import upgrade

app = create_app()

# Corre migraciones al arrancar (idempotente, seguro en Railway)
with app.app_context():
    upgrade()