# app/cli.py
import os
from flask import Flask
from .extensions import db
from .models import User


def register_cli(app: Flask):
    @app.cli.command("seed_users")
    def seed_users():
        """
        Crea usuarios iniciales si no existen.
        Variables esperadas:
          SEED_USERS = "mau:mau123,david:david123,rulas:rulas123"
          SEED_ADMINS = "mau,david"
        """
        raw = (os.getenv("SEED_USERS") or "").strip()
        admins_raw = (os.getenv("SEED_ADMINS") or "").strip()

        if not raw:
            print("SEED_USERS vacío. Nada que crear.")
            return

        admins = {x.strip() for x in admins_raw.split(",") if x.strip()}

        created = 0
        updated_admins = 0

        for item in [x.strip() for x in raw.split(",") if x.strip()]:
            if ":" not in item:
                print(f"Formato inválido: {item} (usa user:pass)")
                continue

            username, password = item.split(":", 1)
            username = username.strip()
            password = password.strip()

            if not username or not password:
                print(f"Saltado: {item} (username o password vacío)")
                continue

            user = User.query.filter_by(username=username).first()

            if not user:
                user = User(username=username)
                user.set_password(password)
                user.is_admin = username in admins
                db.session.add(user)
                created += 1
                print(f"Creado: {username} (admin={user.is_admin})")
            else:
                # Si ya existe, solo aseguramos el flag admin como lo definimos
                should_be_admin = username in admins
                if user.is_admin != should_be_admin:
                    user.is_admin = should_be_admin
                    updated_admins += 1
                    print(f"Actualizado admin flag: {username} -> admin={should_be_admin}")
                else:
                    print(f"Ya existe: {username} (admin={user.is_admin})")

        db.session.commit()
        print(f"Seed terminado. Creados: {created}. Admin flags actualizados: {updated_admins}.")