from __future__ import annotations

import base64
import io
import json
import os
import re
import zipfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


WHATSAPP_PATTERNS = (
    re.compile(
        r"^\[?(?P<date>\d{1,2}[\/.\-]\d{1,2}[\/.\-]\d{2,4}),?\s+"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(?:-|–)?\s*"
        r"(?P<author>[^:]{1,80}):\s*(?P<message>.*)$"
    ),
)

AUTOMOTIVE_KEYWORDS = {
    "aceite", "fuga", "motor", "clutch", "embrague", "radiador",
    "anticongelante", "refrigerante", "calent", "termostato", "ventilador",
    "motoventilador", "freno", "balata", "pastilla", "disco", "rotor",
    "suspension", "suspensión", "amortiguador", "buje", "rotula", "rótula",
    "alineacion", "alineación", "alternador", "bateria", "batería", "fusible",
    "sensor", "inyector", "bujia", "bujía", "direccion", "dirección", "servicio",
    "mantenimiento", "diagnostico", "diagnóstico", "scanner", "escáner", "código",
    "codigo", "verificacion", "verificación", "catalizador", "llanta", "retén",
    "reten", "cigüeñal", "cigueñal", "bomba", "carter", "cárter", "manguera",
    "toma de agua", "deposito", "depósito", "check engine",
}

CATEGORIES = (
    ("Enfriamiento", ("anticongelante", "refrigerante", "radiador", "calent", "termostato", "motoventilador", "ventilador", "toma de agua", "depósito", "deposito")),
    ("Motor", ("motor", "inyector", "sensor", "buj", "cigueñal", "cigüeñal", "carter", "cárter", "aceite", "p1338", "p0341", "p0420")),
    ("Frenos", ("freno", "balata", "pastilla", "disco", "rotor")),
    ("Suspensión", ("suspension", "suspensión", "amortiguador", "buje", "rotula", "rótula", "aline")),
    ("Eléctrico", ("alternador", "bateria", "batería", "fusible", "arnes", "arnés", "eléctr", "electr")),
    ("Transmisión", ("clutch", "embrague", "transmision", "transmisión", "caja")),
    ("Llantas", ("llanta", "neumatic", "neumát")),
    ("Mantenimiento", ("servicio", "mantenimiento", "afinacion", "afinación")),
)

TITLE_BY_CATEGORY = {
    "Enfriamiento": "Sistema de enfriamiento",
    "Motor": "Motor / diagnóstico",
    "Frenos": "Sistema de frenos",
    "Suspensión": "Suspensión / dirección",
    "Eléctrico": "Sistema eléctrico",
    "Transmisión": "Transmisión / clutch",
    "Llantas": "Llantas",
    "Mantenimiento": "Servicio / mantenimiento",
    "Reparación": "Intervención mecánica",
}


@dataclass
class ImportCandidate:
    source_type: str
    date: str | None
    title: str
    category: str
    cost: int | None
    odometer_km: int | None
    codes: list[str]
    excerpt: str
    confidence: int
    evidence_count: int = 1
    source_file: str | None = None
    source_actor: str = "owner"
    verification_status: str = "ai_candidate"

    def to_dict(self) -> dict:
        return asdict(self)


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def _number(value: str | None) -> int | None:
    digits = re.sub(r"[^\d]", "", value or "")
    return int(digits) if digits else None


def _extract_cost(text: str) -> int | None:
    patterns = (
        r"\$\s*([\d]{1,3}(?:[,.]\d{3})+|\d{3,6})(?!\s*(?:km|kms))",
        r"([\d]{1,3}(?:[,.]\d{3})+|\d{3,6})\s*(?:pesos|mxn)\b",
        r"(?:total|fueron|queda(?:ría)?|sale(?:n)?|costo|precio)\D{0,14}([\d]{3,6}(?:[,.]\d{3})?)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = _number(match.group(1))
            if value and 50 <= value <= 2_000_000:
                return value
    return None


def _extract_odometer(text: str) -> int | None:
    match = re.search(r"\b(\d{2,3}(?:[,.]\d{3})+|\d{5,7})\s*(?:km|kms|kil[oó]metros)\b", text, re.I)
    value = _number(match.group(1)) if match else None
    return value if value and 1_000 <= value <= 3_000_000 else None


def _extract_codes(text: str) -> list[str]:
    return sorted(set(re.findall(r"\bP\d{4}\b", text.upper())))


def _category(text: str) -> str:
    low = text.lower()
    for category, needles in CATEGORIES:
        if any(needle in low for needle in needles):
            return category
    return "Reparación"


def _relevance(text: str) -> int:
    low = text.lower()
    score = min(sum(1 for keyword in AUTOMOTIVE_KEYWORDS if keyword in low), 4)
    score += 2 if _extract_cost(text) else 0
    score += 2 if _extract_odometer(text) else 0
    score += 2 if _extract_codes(text) else 0
    if any(word in low for word in ("cambiar", "reemplazar", "reparar", "cotiz", "pendiente", "falla", "tirando", "prende", "arranca")):
        score += 1
    return score


def _parse_date(raw: str) -> str | None:
    cleaned = raw.replace(".", "/").replace("-", "/")
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.date().isoformat()
        except ValueError:
            pass
    return None


def parse_whatsapp_text(text: str, filename: str = "WhatsApp.txt") -> dict:
    messages: list[dict] = []
    current: dict | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip("\ufeff")
        match = WHATSAPP_PATTERNS[0].match(line)
        if match:
            if current:
                messages.append(current)
            current = {
                "date": _parse_date(match.group("date")),
                "time": match.group("time"),
                "author": match.group("author").strip(),
                "message": match.group("message").strip(),
            }
        elif current and line.strip():
            current["message"] += "\n" + line.strip()
    if current:
        messages.append(current)

    participants = sorted({m["author"] for m in messages if m.get("author")})
    dates = [m["date"] for m in messages if m.get("date")]
    grouped: dict[str, list[dict]] = defaultdict(list)

    for message in messages:
        relevance = _relevance(message["message"])
        if relevance >= 2:
            item = dict(message)
            item["relevance"] = relevance
            grouped[message.get("date") or "sin-fecha"].append(item)

    candidates: list[ImportCandidate] = []
    for day, items in grouped.items():
        combined = "\n".join(f'{item["author"]}: {item["message"]}' for item in items)
        cost = next((_extract_cost(item["message"]) for item in reversed(items) if _extract_cost(item["message"])), None)
        km = next((_extract_odometer(item["message"]) for item in reversed(items) if _extract_odometer(item["message"])), None)
        codes = _extract_codes(combined)
        category = _category(combined)
        score = sum(item["relevance"] for item in items)
        confidence = min(97, 48 + score * 4 + (7 if cost else 0) + (6 if km else 0) + (5 if codes else 0))
        candidates.append(ImportCandidate(
            source_type="whatsapp_export",
            date=None if day == "sin-fecha" else day,
            title=TITLE_BY_CATEGORY.get(category, "Intervención mecánica"),
            category=category,
            cost=cost,
            odometer_km=km,
            codes=codes,
            excerpt=combined[:900],
            confidence=max(48, confidence),
            evidence_count=len(items),
            source_file=filename,
        ))

    candidates.sort(key=lambda item: (item.date or "", item.confidence), reverse=True)
    return {
        "kind": "whatsapp",
        "source_file": filename,
        "messages": len(messages),
        "participants": participants,
        "date_from": min(dates) if dates else None,
        "date_to": max(dates) if dates else None,
        "candidate_groups": len(candidates),
        "candidates": [candidate.to_dict() for candidate in candidates[:30]],
        "warnings": [] if messages else ["No se reconoció el formato del export de WhatsApp."],
    }


def parse_whatsapp_zip(data: bytes, filename: str) -> dict:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return {"kind": "archive", "source_file": filename, "candidates": [], "warnings": ["El ZIP no es válido."]}

    with archive:
        names = archive.namelist()
        txt_names = [name for name in names if name.lower().endswith(".txt")]
        if not txt_names:
            return {"kind": "whatsapp", "source_file": filename, "messages": 0, "candidates": [], "attachments": len(names), "warnings": ["El ZIP no contiene el .txt del chat."]}
        txt_names.sort(key=lambda name: ("chat" not in name.lower() and "whatsapp" not in name.lower(), -archive.getinfo(name).file_size))
        chat_name = txt_names[0]
        result = parse_whatsapp_text(_decode_bytes(archive.read(chat_name)), f"{filename} → {Path(chat_name).name}")
        result["attachments"] = sum(1 for name in names if not name.endswith("/") and name != chat_name)
        result["archive_files"] = len(names)
        return result


def _candidate_from_text(text: str, filename: str, source_type: str) -> ImportCandidate:
    category = _category(text)
    return ImportCandidate(
        source_type=source_type,
        date=None,
        title=TITLE_BY_CATEGORY.get(category, "Intervención mecánica"),
        category=category,
        cost=_extract_cost(text),
        odometer_km=_extract_odometer(text),
        codes=_extract_codes(text),
        excerpt=re.sub(r"\s+", " ", text).strip()[:1200],
        confidence=min(92, 44 + _relevance(text) * 6),
        source_file=filename,
        source_actor="workshop",
    )


def parse_text_document(data: bytes, filename: str) -> dict:
    text = _decode_bytes(data)
    recognized_lines = sum(1 for line in text.splitlines() if WHATSAPP_PATTERNS[0].match(line))
    if recognized_lines >= 3:
        return parse_whatsapp_text(text, filename)
    candidate = _candidate_from_text(text, filename, "text_note")
    return {"kind": "document", "source_file": filename, "characters": len(text), "candidates": [candidate.to_dict()], "warnings": []}


def parse_pdf(data: bytes, filename: str) -> dict:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:
        return {"kind": "document", "source_file": filename, "candidates": [], "warnings": [f"No se pudo leer el PDF: {type(exc).__name__}"]}
    if not text:
        return {"kind": "document", "source_file": filename, "pages": len(reader.pages), "candidates": [], "warnings": ["El PDF parece escaneado; conviene procesarlo con Vision AI."]}
    candidate = _candidate_from_text(text, filename, "workshop_pdf")
    return {"kind": "document", "source_file": filename, "pages": len(reader.pages), "characters": len(text), "candidates": [candidate.to_dict()], "warnings": []}


def parse_image_with_ai(data: bytes, filename: str, mime: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"kind": "image", "source_file": filename, "candidates": [], "warnings": ["Vision AI no está configurada en esta preview."]}

    if mime not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        mime = "image/jpeg"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        image_b64 = base64.standard_b64encode(data).decode()
        instruction = """Analiza esta nota, recibo u orden de taller automotriz. Devuelve SOLO JSON válido: {\"date\":\"YYYY-MM-DD o null\",\"title\":\"resumen corto\",\"category\":\"Mantenimiento|Enfriamiento|Motor|Frenos|Suspensión|Eléctrico|Transmisión|Llantas|Reparación\",\"cost\":1234 o null,\"odometer_km\":123456 o null,\"codes\":[\"P0420\"],\"work_items\":[\"trabajo\"],\"pending_items\":[\"pendiente\"],\"confidence\":0}. No inventes datos; usa null o [] si no se lee."""
        message = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=700,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": image_b64}},
                {"type": "text", "text": instruction},
            ]}],
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S)
        payload = json.loads(raw)
        excerpt = []
        if payload.get("work_items"):
            excerpt.append("Trabajos: " + ", ".join(map(str, payload["work_items"])))
        if payload.get("pending_items"):
            excerpt.append("Pendientes: " + ", ".join(map(str, payload["pending_items"])))
        candidate = ImportCandidate(
            source_type="workshop_image_ai",
            date=payload.get("date"),
            title=payload.get("title") or "Nota de taller",
            category=payload.get("category") or "Reparación",
            cost=payload.get("cost"),
            odometer_km=payload.get("odometer_km"),
            codes=sorted(set(payload.get("codes") or [])),
            excerpt=" · ".join(excerpt) or "Documento interpretado con Vision AI.",
            confidence=max(0, min(100, int(payload.get("confidence") or 60))),
            source_file=filename,
            source_actor="workshop",
        )
        return {"kind": "image", "source_file": filename, "candidates": [candidate.to_dict()], "warnings": [], "ai_used": True}
    except Exception as exc:
        return {"kind": "image", "source_file": filename, "candidates": [], "warnings": [f"Vision AI no pudo interpretar la imagen: {type(exc).__name__}"]}


def inspect_upload(data: bytes, filename: str, mime: str = "") -> dict:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".zip":
        return parse_whatsapp_zip(data, filename)
    if suffix == ".txt":
        return parse_text_document(data, filename)
    if suffix == ".pdf":
        return parse_pdf(data, filename)
    if suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"):
        return parse_image_with_ai(data, filename, mime)
    return {"kind": "unknown", "source_file": filename, "candidates": [], "warnings": ["Formato no soportado todavía. Usa ZIP/TXT de WhatsApp, PDF o imagen."]}
