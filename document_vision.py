# -*- coding: utf-8 -*-
"""
document_vision.py — Respaldo por VISIÓN (Claude) para CTL, CUS y Poder
Forestal cuando el archivo es un escaneo/foto SIN texto real.

extract_text_from_file() (pypdf) solo lee texto que ya existe en el PDF —
si el documento es una foto o un escaneo puro (muy común en CTL viejos,
CUS firmados y escaneados, etc.), pypdf devuelve texto vacío y todo el
resto del pipeline (analyzer.py, ctl_cus_checker.py) se queda sin nada que
analizar. Este módulo rasteriza el PDF/imagen y usa la API de visión de
Claude para leer directamente los mismos campos que se buscarían por regex
en un documento con texto — matrícula, titular/propietario, municipio.

Se usa SOLO como respaldo: app.py lo invoca únicamente cuando
extract_text_from_file() no devolvió texto aprovechable para ese archivo.
"""

import base64
import io
import json
import os
import re
from typing import Optional


# ---------------------------------------------------------------------------
# RASTERIZACIÓN (mismo enfoque que cedula_checker.py)
# ---------------------------------------------------------------------------

def _rasterizar_pdf(pdf_bytes: bytes, max_paginas: int = 4, dpi: int = 180) -> list:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []
    imagenes = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        n = min(max_paginas, len(doc))
        for i in range(n):
            page = doc[i]
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            imagenes.append(base64.b64encode(pix.tobytes("png")).decode())
        doc.close()
    except Exception:
        return []
    return imagenes


_EXT_MEDIA_TYPE = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "webp": "image/webp", "gif": "image/gif",
}


def _preparar_imagenes(file_bytes: bytes, filename: str, max_paginas: int = 4) -> list:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if file_bytes[:4] == b"%PDF" or file_bytes[:5] == b"%PDF-":
        return [(b64, "image/png") for b64 in _rasterizar_pdf(file_bytes, max_paginas)]
    if ext in _EXT_MEDIA_TYPE:
        return [(base64.b64encode(file_bytes).decode(), _EXT_MEDIA_TYPE[ext])]
    if file_bytes[:8].startswith(b"\x89PNG"):
        return [(base64.b64encode(file_bytes).decode(), "image/png")]
    if file_bytes[:3] == b"\xff\xd8\xff":
        return [(base64.b64encode(file_bytes).decode(), "image/jpeg")]
    return []


# ---------------------------------------------------------------------------
# LLAMADA GENÉRICA A LA API DE VISIÓN
# ---------------------------------------------------------------------------

def _obtener_api_key() -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


def _llamar_vision_json(imagenes: list, prompt: str, max_tokens: int = 700, timeout: int = 45) -> dict:
    import urllib.request

    api_key = _obtener_api_key()
    if not api_key or not imagenes:
        return {}

    content = [
        {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}}
        for b64, mt in imagenes
    ]
    content.append({"type": "text", "text": prompt})

    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            texto = data["content"][0]["text"].strip()
            texto = re.sub(r"```json|```", "", texto).strip()
            return json.loads(texto)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# PROMPTS POR TIPO DE DOCUMENTO
# ---------------------------------------------------------------------------

_PROMPT_CTL = """Estás viendo un Certificado de Tradición y Libertad de Matrícula \
Inmobiliaria (Colombia), posiblemente de varias páginas con un historial de \
anotaciones (compraventas, embargos, hipotecas, cancelaciones).

Identifica:
1. El número de matrícula inmobiliaria (formato tipo "347-3480").
2. TODOS los TITULARES VIGENTES del derecho real de dominio. Recorre las \
anotaciones en orden: en cada compraventa, adjudicación, donación o venta \
de derechos de cuota, quien aparece en "DE:" deja de ser dueño (salvo que \
venda solo parte de su cuota) y quienes aparecen en "A:" con X pasan a \
serlo. Ignora hipotecas, cancelaciones y embargos. Si hay copropietarios \
(sucesión, cuotas), incluye a todos, no solo a los de la última anotación.
3. El municipio donde está ubicado el predio.

Responde SOLO con JSON sin backticks: {"matricula": "string o null", \
"titulares": [{"nombre": "string", "numero_id": "string o null"}], \
"municipio": "string o null"}"""

_PROMPT_CUS = """Estás viendo un Certificado de Uso del Suelo (Colombia), \
emitido por una Secretaría de Planeación municipal.

Identifica:
1. El número de matrícula inmobiliaria si aparece mencionado.
2. El municipio que expide el certificado.

Responde SOLO con JSON sin backticks: {"matricula": "string o null", \
"municipio": "string o null"}"""

_PROMPT_PODER = """Estás viendo un Poder Forestal (documento donde el \
propietario de un predio autoriza a un tercero a tramitar un aprovechamiento \
forestal ante la autoridad ambiental).

Identifica:
1. Los nombres completos de TODOS los propietarios/poderdantes (quienes \
OTORGAN el poder; puede haber varios copropietarios). No incluyas al \
apoderado ni a la empresa que recibe el poder.
2. El número de matrícula inmobiliaria del predio, si se menciona.

Responde SOLO con JSON sin backticks: {"poderdantes": [{"nombre": "string", \
"numero_id": "string o null"}], "matricula": "string o null"}"""


# ---------------------------------------------------------------------------
# PUNTOS DE ENTRADA
# ---------------------------------------------------------------------------

def extraer_ctl_vision(file_bytes: bytes, filename: str) -> dict:
    imagenes = _preparar_imagenes(file_bytes, filename, max_paginas=4)
    r = _llamar_vision_json(imagenes, _PROMPT_CTL)
    titulares = [{"nombre": t.get("nombre", "").strip(), "tipo_id": "",
                  "numero_id": re.sub(r"\D", "", str(t.get("numero_id") or ""))}
                 for t in (r.get("titulares") or []) if isinstance(t, dict) and t.get("nombre")]
    return {
        "matricula": r.get("matricula"),
        "titulares": titulares,
        "propietario": ", ".join(t["nombre"] for t in titulares) or r.get("propietario"),
        "municipio": r.get("municipio"),
    }


def extraer_cus_vision(file_bytes: bytes, filename: str) -> dict:
    imagenes = _preparar_imagenes(file_bytes, filename, max_paginas=2)
    r = _llamar_vision_json(imagenes, _PROMPT_CUS)
    return {
        "matricula": r.get("matricula"),
        "municipio": r.get("municipio"),
    }


def extraer_poder_vision(file_bytes: bytes, filename: str) -> dict:
    imagenes = _preparar_imagenes(file_bytes, filename, max_paginas=3)
    r = _llamar_vision_json(imagenes, _PROMPT_PODER)
    poderdantes = [{"nombre": p.get("nombre", "").strip(), "tipo_id": "",
                    "numero_id": re.sub(r"\D", "", str(p.get("numero_id") or ""))}
                   for p in (r.get("poderdantes") or []) if isinstance(p, dict) and p.get("nombre")]
    return {
        "personas": poderdantes,
        "propietario": ", ".join(p["nombre"] for p in poderdantes) or r.get("propietario"),
        "matricula": r.get("matricula"),
    }
