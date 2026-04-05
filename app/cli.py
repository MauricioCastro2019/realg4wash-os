# app/cli.py
import os
from flask import Flask
from .extensions import db
from .models import User, ServiceCatalog


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

    @app.cli.command("seed_catalog")
    def seed_catalog():
        """
        Pobla ServiceCatalog con los 50+ servicios del catálogo G4.
        Precios con +10% sobre base estratégica. Actualiza si ya existe.
        """
        # fmt: off
        # (code, name, category, tier, price_auto, price_camioneta, price_moto, duration_min)
        SERVICES = [
            # ── EXTERIORES BÁSICOS ─────────────────────────────────────
            ("EXT-BASE",         "Lavado exterior básico",              "ext", "basic",   55,  70,  55, 12),
            ("EXT-ENJUAGUE",     "Enjuague a presión",                  "ext", "basic",   30,  35,  25,  5),
            ("EXT-SECADO-MF",    "Secado con microfibra",               "ext", "basic",   30,  35,  25,  8),
            ("EXT-SECADO-AIRE",  "Secado con aire a presión",           "ext", "basic",   45,  55,  35,  8),
            ("EXT-RINES-BASE",   "Limpieza de rines básica",            "ext", "basic",   35,  45,  30,  8),
            ("EXT-LLANTAS",      "Limpieza de llantas",                 "ext", "basic",   35,  45,  30,  8),
            ("EXT-EMBLEMAS",     "Detallado de emblemas",               "ext", "basic",   45,  45,   0,  5),
            # ── EXTERIORES MEDIOS ──────────────────────────────────────
            ("EXT-SHAMPOO",      "Lavado exterior + shampoo especializado","ext","mid",   90, 110,  70, 15),
            ("EXT-PRELAVADO",    "Prelavado con espuma activa",         "ext", "mid",    50,  60,  40,  8),
            ("EXT-SOPLETEADO",   "Sopleteado de interiores",            "ext", "mid",    50,  60,  40,  8),
            ("EXT-RINES-PROF",   "Lavado profundo de rines",            "ext", "mid",    80, 100,  60, 12),
            ("EXT-LLANTAS-PROF", "Lavado profundo de llantas",          "ext", "mid",    65,  85,  50, 10),
            ("EXT-FASIAS",       "Lavado profundo de fascias",          "ext", "mid",    65,  90,   0, 10),
            ("EXT-VINIL",        "Protección de llantas (brillo)",      "ext", "mid",    50,  60,  40,  8),
            ("EXT-PLAST-EXT",    "Pulido de plásticos exteriores",      "ext", "mid",   100, 120,   0, 15),
            ("EXT-ACOND-EXT",    "Acondicionador de plásticos ext.",    "ext", "mid",    80,  95,   0, 10),
            ("EXT-CRISTALES-EXT","Cristales exteriores antigragotas",   "ext", "mid",    80,  95,  60, 10),
            ("EXT-BISAGRAS",     "Limpieza de bisagras y zonas ocultas","ext", "mid",    50,  60,   0,  8),
            # ── EXTERIORES PREMIUM ─────────────────────────────────────
            ("EXT-MOTOR",        "Lavado de motor",                     "ext", "premium",165, 200,   0, 25),
            ("EXT-FAROS-PULIDO", "Pulido de faros",                     "ext", "premium",130, 130,   0, 20),
            ("EXT-FAROS-ACRILICO","Acrílico en faros",                  "ext", "premium", 90,  90,   0, 15),
            ("EXT-SHOWROOM",     "Detallado completo tipo showroom",    "ext", "premium",550, 715,   0,120),
            ("EXT-ECOLOGICO",    "Lavado ecológico (bajo consumo agua)","ext", "premium",110, 130,  90, 20),
            # ── INTERIORES BÁSICOS ─────────────────────────────────────
            ("INT-ASPIRADO",     "Aspirado general interior",           "int", "basic",   55,  70,  40, 12),
            ("INT-TAPETES",      "Limpieza de tapetes",                 "int", "basic",   40,  50,   0,  8),
            ("INT-CAJUELA",      "Limpieza de cajuela",                 "int", "basic",   40,  50,   0,  5),
            ("INT-TABLERO",      "Limpieza de tablero",                 "int", "basic",   35,  40,   0,  5),
            ("INT-CONSOLA",      "Limpieza de consola central",         "int", "basic",   35,  40,   0,  5),
            ("INT-PUERTAS",      "Limpieza de puertas interiores",      "int", "basic",   35,  45,   0,  5),
            ("INT-PORTAVASOS",   "Limpieza de portavasos",              "int", "basic",   25,  25,   0,  3),
            ("INT-VENTILAS",     "Limpieza de ventilas A/C",            "int", "basic",   30,  30,   0,  5),
            ("INT-BOTONES",      "Limpieza de botones y controles",     "int", "basic",   30,  30,   0,  4),
            ("INT-VOLANTE",      "Limpieza de volante",                 "int", "basic",   35,  35,  25,  4),
            ("INT-PEDALES",      "Limpieza de pedales",                 "int", "basic",   30,  30,  20,  3),
            ("INT-CINTURONES",   "Limpieza de cinturones de seguridad", "int", "basic",   35,  40,   0,  5),
            ("INT-RIELES",       "Limpieza de rieles de asientos",      "int", "basic",   30,  35,   0,  5),
            ("INT-COMPARTIMENTOS","Limpieza de compartimentos internos","int", "basic",   25,  30,   0,  3),
            ("INT-MARCOS",       "Limpieza de marcos de puertas",       "int", "basic",   40,  50,   0,  5),
            ("INT-AROMATIZANTE", "Aromatizante básico",                 "int", "basic",   25,  25,  25,  1),
            ("INT-AROMATIZANTE-P","Aromatizante premium (elección)",    "int", "mid",     45,  45,  45,  2),
            # ── INTERIORES MEDIOS ──────────────────────────────────────
            ("INT-PLASTICOS",    "Limpieza de plásticos interiores",    "int", "mid",     60,  80,   0, 10),
            ("INT-ACOND-PLAST",  "Acondicionador de plásticos int.",    "int", "mid",     70,  90,   0,  8),
            ("INT-PROTECCION-UV","Protección UV interiores",            "int", "mid",     80,  95,   0,  8),
            ("INT-ALFOMBRA-BASE","Limpieza de alfombra",                "int", "mid",     70,  90,   0, 12),
            ("INT-ASIENTOS-TELA","Limpieza de asientos tela",           "int", "mid",     90, 110,   0, 15),
            ("INT-CIELO",        "Limpieza de cielo/toldo",             "int", "mid",     90, 110,   0, 15),
            ("INT-CINTURONES-RET","Limpieza de cinturones retráctiles", "int", "mid",     40,  45,   0,  5),
            ("INT-CRISTALES-INT","Cristales interiores antiempañante",  "int", "mid",     65,  85,   0,  8),
            ("INT-DESINFECCION", "Desinfección interior antibacterial", "int", "mid",     80,  95,  60,  8),
            ("INT-DRENAJES",     "Limpieza de drenajes de carrocería",  "int", "mid",     50,  60,   0,  8),
            # ── INTERIORES PREMIUM ─────────────────────────────────────
            ("INT-ASIENTOS-PIEL","Limpieza de asientos piel",           "int", "premium",145, 175,   0, 20),
            ("INT-VAPOR-ASIENTOS","Vapor en asientos",                  "int", "premium",175, 220,   0, 25),
            ("INT-ALFOMBRA-PROF","Lavado profundo de alfombra",         "int", "premium",145, 175,   0, 20),
            ("INT-VAPOR-COMPLETO","Vapor interior completo",            "int", "premium",275, 350,   0, 45),
            ("INT-OZONO",        "Eliminación de olores (ozono)",       "int", "premium",130, 130,   0, 20),
            ("INT-ASIENTOS-VP",  "Asientos + vapor (paquete completo)", "int", "premium",245, 310,   0, 50),
            ("INT-DESMONTAJE",   "Limpieza profunda con desmontaje",    "int", "premium",220, 275,   0, 45),
            # ── ESPECIALES ────────────────────────────────────────────
            ("EVAL-ESTETICA",    "Valoración estética general",         "special","basic",  0,   0,   0,  5),
        ]
        # fmt: on

        created = 0
        updated = 0

        for row in SERVICES:
            code, name, cat, tier, pa, pc, pm, dur = row
            svc = ServiceCatalog.query.get(code)
            if svc:
                svc.name = name
                svc.category = cat
                svc.tier = tier
                svc.price_auto = pa
                svc.price_camioneta = pc
                svc.price_moto = pm
                svc.duration_min = dur
                updated += 1
            else:
                svc = ServiceCatalog(
                    code=code, name=name, category=cat, tier=tier,
                    price_auto=pa, price_camioneta=pc, price_moto=pm,
                    duration_min=dur,
                )
                db.session.add(svc)
                created += 1

        db.session.commit()
        print(f"Catálogo cargado. Creados: {created}. Actualizados: {updated}.")