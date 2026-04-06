from flask import Flask
from dotenv import load_dotenv

from .config import Config
from .extensions import db, migrate, login_manager


def create_app():
    load_dotenv()

    app = Flask(__name__)
    app.config.from_object(Config)

    # Extensiones
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Blueprints
    from .auth import auth_bp
    from .main import main_bp
    from .inventory import inventory_bp
    from .agenda import agenda_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(agenda_bp)

    # CLI commands (seed_users, etc.)
    from .cli import register_cli
    register_cli(app)

    return app