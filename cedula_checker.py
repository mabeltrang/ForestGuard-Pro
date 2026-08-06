# -*- coding: utf-8 -*-
"""
cedula_checker.py — Extrae nombre y número de identificación (C.C./C.E./NIT)
desde una FOTO o PDF ESCANEADO del documento de identidad del propietario
(algo que propietario_checker.py NO puede hacer, porque ese módulo solo lee
texto real de un .docx/.xlsx con pypdf/openpyxl — no hace OCR ni visión).

Este módulo:
  1. Acepta imagen (jpg/jpeg/png/webp) o PDF (rasteriza la primera página,
     y una segunda si existe, por si la cédula viene en dos caras/páginas).
  2. Llama a Claude (vision) para leer nombre completo y número de
     identificación tal como aparecen en el documento.
  3. Compara ese resultado contra:
       - los propietarios detectados en el Plan/Informe de Aprovechamiento
         (propietario_checker.extraer_propietarios_docx), comparando
         PRIMERO por número de identificación (más confiable que el nombre)
         y si no hay match exacto, por similitud de nombre.
       - el valor de PROPIETARIO del Inventario Forestal (xlsx), por nombre.

Requiere ANTHROPIC_API_KEY (env var o st.secrets), igual que vision_checker.py.
"""

import base64
import io
import json
import os
import re
import unicodedata
from typing import Optional


# ---------------------------------------------------------------------------
# UTILIDADES DE NORMALIZACIÓN / COMPARACIÓN
# ---------------------------------------------------------------------------

def _normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^A-Za-z0-9 ]", " ", texto)
    return " ".join(texto.upper().split())


def _normalizar_numero_id(numero: str) -> str:
    """Deja solo dígitos, para comparar '43.081.891' == '43081891' == '43,081,891'."""
    return re.sub(r"\D", "", numero or "")


def _similitud_nombre(a: str, b: str) -> float:
    import difflib
    a_norm, b_norm = _normalizar_texto(a), _normalizar_texto(b)
    if not a_norm or not b_norm:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a_norm, b_norm).ratio()
    if a_norm in b_norm or b_norm in a_norm:
        ratio = max(ratio, 0.9)
    return ratio


# ---------------------------------------------------------------------------
# RASTERIZACIÓN (PDF -> imágenes) / LECTURA DE IMAGEN DIRECTA
# ---------------------------------------------------------------------------

def _rasterizar_pdf(pdf_bytes: bytes, max_paginas: int = 2, dpi: int = 200) -> list:
    """Retorna hasta `max_paginas` imágenes (base64 PNG) de un PDF escaneado."""
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
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


def _preparar_imagenes(file_bytes: bytes, filename: str) -> list:
    """
    Retorna lista de (imagen_b64, media_type) lista para mandar a la API,
    ya sea que el archivo sea una imagen directa o un PDF escaneado.
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if file_bytes[:4] == b"%PDF" or file_bytes[:5] == b"%PDF-":
        return [(b64, "image/png") for b64 in _rasterizar_pdf(file_bytes)]

    if ext in _EXT_MEDIA_TYPE:
        return [(base64.b64encode(file_bytes).decode(), _EXT_MEDIA_TYPE[ext])]

    # Fallback: header de imagen conocido aunque la extensión no lo diga
    if file_bytes[:8].startswith(b"\x89PNG"):
        return [(base64.b64encode(file_bytes).decode(), "image/png")]
    if file_bytes[:3] == b"\xff\xd8\xff":
        return [(base64.b64encode(file_bytes).decode(), "image/jpeg")]

    return []


# ---------------------------------------------------------------------------
# LLAMADA A LA API DE VISIÓN
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


_PROMPT_CEDULA = """Eres un asistente que lee documentos de identidad colombianos \
(Cédula de Ciudadanía, Cédula de Extranjería, NIT/Cámara de Comercio, Pasaporte) \
a partir de una foto o escaneo, para validar trámites ambientales/forestales.

Observa la(s) imagen(es) adjunta(s) (puede ser el anverso y reverso del mismo \
documento) y extrae:

1. Nombre completo de la persona (o razón social si es NIT/persona jurídica), \
tal como aparece impreso.
2. Número de identificación completo (con puntos si así aparece).
3. Tipo de documento: "CC" (cédula de ciudadanía), "CE" (cédula de extranjería), \
"NIT", "PASAPORTE" u "OTRO".
4. Si la imagen NO corresponde a un documento de identidad, indícalo.

Responde SOLO con JSON sin backticks ni texto adicional, con esta estructura exacta:
{
  "es_documento_identidad": true|false,
  "nombre": "string o null",
  "numero_identificacion": "string o null",
  "tipo_documento": "CC|CE|NIT|PASAPORTE|OTRO|null",
  "confianza": "alta|media|baja",
  "observaciones": "cualquier duda sobre la legibilidad, ej. imagen borrosa"
}"""


def _llamar_api_vision_cedula(imagenes: list) -> dict:
    import urllib.request

    api_key = _obtener_api_key()
    if not api_key:
        return {
            "es_documento_identidad": None,
            "nombre": None,
            "numero_identificacion": None,
            "tipo_documento": None,
            "confianza": "baja",
            "observaciones": (
                "Falta configurar ANTHROPIC_API_KEY (variable de entorno o "
                "st.secrets en Streamlit Cloud) — sin esto no se puede leer la cédula."
            ),
        }

    content = []
    for img_b64, media_type in imagenes:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": img_b64},
        })
    content.append({"type": "text", "text": _PROMPT_CEDULA})

    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 500,
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            texto_respuesta = data["content"][0]["text"].strip()
            texto_respuesta = re.sub(r"```json|```", "", texto_respuesta).strip()
            return json.loads(texto_respuesta)
    except Exception as e:
        return {
            "es_documento_identidad": None,
            "nombre": None,
            "numero_identificacion": None,
            "tipo_documento": None,
            "confianza": "baja",
            "observaciones": f"No se pudo leer el documento: {e}",
        }


# ---------------------------------------------------------------------------
# PUNTO DE ENTRADA — EXTRACCIÓN
# ---------------------------------------------------------------------------

def extraer_datos_cedula(file_bytes: bytes, filename: str) -> dict:
    """
    Extrae {nombre, numero_identificacion, tipo_documento, confianza,
    es_documento_identidad, observaciones} desde una foto o PDF del
    documento de identidad.
    """
    imagenes = _preparar_imagenes(file_bytes, filename)
    if not imagenes:
        return {
            "es_documento_identidad": None,
            "nombre": None,
            "numero_identificacion": None,
            "tipo_documento": None,
            "confianza": "baja",
            "observaciones": (
                "Formato no soportado o PyMuPDF no disponible para rasterizar el "
                "PDF (instala pymupdf) — sube una imagen (jpg/png) o un PDF con "
                "página escaneada."
            ),
        }
    return _llamar_api_vision_cedula(imagenes)


# ---------------------------------------------------------------------------
# COMPARACIÓN CONTRA PLAN/INFORME AF Y CONTRA INVENTARIO
# ---------------------------------------------------------------------------

def comparar_cedula_con_propietario(
    datos_cedula: dict,
    propietarios_plan: Optional[list] = None,
    propietario_inventario: Optional[str] = None,
    umbral_nombre: float = 0.6,
) -> dict:
    """
    datos_cedula: salida de extraer_datos_cedula().
    propietarios_plan: salida de propietario_checker.extraer_propietarios_docx()
                        -> [{"nombre","tipo_id","numero_id"}, ...]
    propietario_inventario: valor crudo de la celda PROPIETARIO del xlsx.

    Retorna:
    {
      "coincide_plan": bool|None,        # por número de identificación (o nombre si no hay match numérico)
      "criterio_plan": "numero_id"|"nombre"|None,
      "mejor_match_plan": {"nombre","tipo_id","numero_id"}|None,
      "coincide_inventario": bool|None,  # por nombre (el inventario normalmente no trae número de ID)
      "similitud_inventario": float|None,
    }
    """
    propietarios_plan = propietarios_plan or []
    numero_cedula_norm = _normalizar_numero_id(datos_cedula.get("numero_identificacion") or "")
    nombre_cedula = datos_cedula.get("nombre") or ""

    resultado = {
        "coincide_plan": None,
        "criterio_plan": None,
        "mejor_match_plan": None,
        "coincide_inventario": None,
        "similitud_inventario": None,
    }

    # --- Comparación contra el Plan/Informe AF ---
    if numero_cedula_norm and propietarios_plan:
        for p in propietarios_plan:
            if _normalizar_numero_id(p.get("numero_id", "")) == numero_cedula_norm:
                resultado["coincide_plan"] = True
                resultado["criterio_plan"] = "numero_id"
                resultado["mejor_match_plan"] = p
                break
        else:
            resultado["coincide_plan"] = False
            resultado["criterio_plan"] = "numero_id"

    # Si no hubo match (o no comparación) por número, probar por nombre
    if resultado["coincide_plan"] in (None, False) and nombre_cedula and propietarios_plan:
        mejor_ratio, mejor_p = 0.0, None
        for p in propietarios_plan:
            ratio = _similitud_nombre(nombre_cedula, p.get("nombre", ""))
            if ratio > mejor_ratio:
                mejor_ratio, mejor_p = ratio, p
        if mejor_ratio >= umbral_nombre:
            # Solo sobreescribe un resultado previo "False" por número si el
            # nombre sí concuerda razonablemente bien — se deja constancia
            # de ambos criterios para que el usuario decida.
            if resultado["coincide_plan"] is False:
                resultado["criterio_plan"] = "numero_id (no coincide) + nombre (sí coincide)"
                resultado["coincide_plan"] = None  # ambiguo: requiere revisión manual
            else:
                resultado["coincide_plan"] = True
                resultado["criterio_plan"] = "nombre"
            resultado["mejor_match_plan"] = mejor_p

    # --- Comparación contra el Inventario (solo nombre disponible) ---
    if propietario_inventario and nombre_cedula:
        ratio = _similitud_nombre(nombre_cedula, propietario_inventario)
        resultado["similitud_inventario"] = round(ratio, 2)
        resultado["coincide_inventario"] = ratio >= umbral_nombre

    return resultado


def verificar_cedula_propietario(
    file_bytes: bytes,
    filename: str,
    propietarios_plan: Optional[list] = None,
    propietario_inventario: Optional[str] = None,
) -> dict:
    """Punto de entrada único: lee la cédula y la compara en un solo paso."""
    datos_cedula = extraer_datos_cedula(file_bytes, filename)
    comparacion = comparar_cedula_con_propietario(
        datos_cedula, propietarios_plan, propietario_inventario
    )
    return {**datos_cedula, **comparacion}
