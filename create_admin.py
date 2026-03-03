from app import create_app
from app.extensions import db
from app.models import User

app = create_app()

with app.app_context():
    # Por si acaso: asegura tablas (aunque ya usas migrate)
    db.create_all()

    u = User.query.filter_by(username="admin").first()
    if not u:
        u = User(username="admin", is_admin=True)
        u.set_password("admin123")  # luego lo cambias
        db.session.add(u)
        db.session.commit()
        print("✅ Admin creado: admin / admin123")
    else:
        print("ℹ️ Admin ya existe")