import os
import tempfile
import unittest


_using_temp_sqlite = "DATABASE_URL" not in os.environ
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
if _using_temp_sqlite:
    os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ.setdefault("SECRET_KEY", "test-secret")

from app import create_app  # noqa: E402
from app.garage.memory_store import (  # noqa: E402
    accept_invitation,
    approve_candidates,
    create_onboarding,
    ensure_schema,
    get_invitation,
    list_events,
    list_pending_candidates,
    memory_diagnostics,
    save_import,
)
from app.garage.vehicle_registry import get_vehicle, list_issues  # noqa: E402


class MemoryEngineSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True)
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()
        if _using_temp_sqlite:
            try:
                os.unlink(_tmp.name)
            except OSError:
                pass

    def test_full_owner_consent_memory_flow(self):
        ok, error = ensure_schema()
        self.assertTrue(ok, error)
        diagnostics = memory_diagnostics()
        self.assertTrue(diagnostics["online"], diagnostics)
        self.assertEqual(diagnostics["stage"], "ready")

        created, error = create_onboarding(
            "Cliente Piloto", "Mazda", "3", 2018, "centerfix"
        )
        self.assertIsNone(error)
        self.assertIsNotNone(created)
        token = created["invite_token"]
        vehicle_key = created["vehicle_key"]

        invitation, error = get_invitation(token)
        self.assertIsNone(error)
        self.assertEqual(invitation["status"], "invited")

        invitation, error = accept_invitation(token)
        self.assertIsNone(error)
        self.assertEqual(invitation["status"], "accepted")

        source = {
            "filename": "nota-centerfix.txt",
            "kind": "document",
            "sha256": "a" * 64,
            "byte_size": 120,
            "metadata": {"provider": "CenterFix"},
        }
        candidate = {
            "date": "2026-08-10",
            "title": "Motor / diagnóstico",
            "category": "Motor",
            "cost": 1800,
            "odometer_km": 82350,
            "codes": ["P0420"],
            "excerpt": "Diagnóstico P0420 y servicio realizado.",
            "confidence": 91,
            "evidence_count": 1,
            "source_type": "text_note",
            "source_actor": "workshop",
            "source_file": "nota-centerfix.txt",
        }

        session_id, persisted, error = save_import(vehicle_key, [source], [candidate])
        self.assertIsNone(error)
        self.assertTrue(session_id)
        self.assertEqual(len(persisted), 1)

        pending, error = list_pending_candidates(vehicle_key)
        self.assertIsNone(error)
        self.assertEqual(len(pending), 1)

        approved, error = approve_candidates([pending[0]["id"]])
        self.assertIsNone(error)
        self.assertEqual(approved, 1)

        events, error = list_events(vehicle_key)
        self.assertIsNone(error)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["cost"], 1800)
        self.assertIn("P0420", events[0]["codes"])

        issues, error = list_issues(vehicle_key)
        self.assertIsNone(error)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["code"], "P0420")

        vehicle, error = get_vehicle(vehicle_key)
        self.assertIsNone(error)
        self.assertEqual(vehicle["make"], "Mazda")
        self.assertEqual(vehicle["model"], "3")
        self.assertEqual(vehicle["odometer_km"], 82350)

    def test_reimport_does_not_duplicate_candidate_or_overwrite_identity(self):
        created, error = create_onboarding(
            "Segundo Cliente", "Toyota", "Corolla", 2020, "centerfix"
        )
        self.assertIsNone(error)
        accept_invitation(created["invite_token"])
        vehicle_key = created["vehicle_key"]

        source = {
            "filename": "chat.txt",
            "kind": "whatsapp",
            "sha256": "b" * 64,
            "byte_size": 300,
            "metadata": {},
        }
        candidate = {
            "date": "2026-08-09", "title": "Sistema de frenos", "category": "Frenos",
            "cost": 2500, "odometer_km": 50000, "codes": [], "excerpt": "Cambio de pastillas.",
            "confidence": 85, "evidence_count": 2, "source_type": "whatsapp_export",
            "source_actor": "owner", "source_file": "chat.txt",
        }
        save_import(vehicle_key, [source], [candidate])
        save_import(vehicle_key, [source], [candidate])

        pending, error = list_pending_candidates(vehicle_key)
        self.assertIsNone(error)
        self.assertEqual(len(pending), 1)
        vehicle, error = get_vehicle(vehicle_key)
        self.assertIsNone(error)
        self.assertEqual((vehicle["make"], vehicle["model"]), ("Toyota", "Corolla"))


if __name__ == "__main__":
    unittest.main()
