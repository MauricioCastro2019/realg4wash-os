import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    _db = os.getenv("DATABASE_URL", "sqlite:///" + os.path.join(basedir, "..", "instance", "realg4wash.db"))
    if _db.startswith("postgres://"):
        _db = _db.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = _db
    SQLALCHEMY_TRACK_MODIFICATIONS = False