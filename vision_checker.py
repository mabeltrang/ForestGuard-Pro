"""
vision_checker.py — Verificación de imágenes y mapas en documentos forestales.

Usa la API de Anthropic para analizar visualmente páginas del PDF que contengan
mapas, planos o imágenes, y verifica que la información visual sea coherente con
el texto extraído del paquete.
"""

import base64
import json
import re
import io
import os
from pypdf import PdfReader


# ---------------------------------------------------------------------------
# EXTRACCIÓN DE PÁGINAS CON IMÁGENES
# ---------------------------------------------------------------------------

def _paginas_con_imagenes(pdf_bytes: bytes) -> list[int]:
    """Retorna los índices de páginas que contienen imágenes embebidas."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    paginas = []
    for i, page in enumerate(reader.pages):
        resources = page.get("/Resources")
        if resources:
            if isinstance(resources, dict):
                xobj = resources.get("/XObject", {})
            else:
                xobj = resources.get_object().get("/XObject", {})
            if xobj:
                for key in xobj:
                    obj = xobj[key]
                    if hasattr(obj, "get_object"):
                        obj = obj.get_object()
                    if isinstance(obj, dict) and obj.get("/Subtype") == "/Image":
                        paginas.append(i)
                        break
    return paginas


def _rasterizar_pagina(pdf_bytes: bytes, page_idx: int, dpi: int = 120) -> str | None:
    """
    Rasteriza una página del PDF y retorna base64 PNG.
    Usa pypdf + Pillow si está disponible, sino retorna None.
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[page_idx]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes("png")
        doc.close()
        return base64.b64encode(png_bytes).decode()
    except ImportError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# EXTRACCIÓN DE IMÁGENES EMBEBIDAS EN DOCX
# ---------------------------------------------------------------------------

def _extraer_imagenes_docx(docx_bytes: bytes, max_imagenes: int = 5) -> list[tuple[str, str]]:
    """
    Extrae las imágenes embebidas de un .docx (carpeta word/media/) y las
    retorna como lista de (base64, media_type). Omite formatos vectoriales
    (wmf/emf) que la API de visión no puede leer.
    """
    import zipfile
    imagenes = []
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            media_files = sorted(n for n in z.namelist() if n.startswith("word/media/"))
            for name in media_files:
                ext = name.rsplit(".", 1)[-1].lower()
                if ext == "png":
                    media_type = "image/png"
                elif ext in ("jpg", "jpeg"):
                    media_type = "image/jpeg"
                elif ext == "gif":
                    media_type = "image/gif"
                elif ext == "webp":
                    media_type = "image/webp"
                else:
                    continue  # wmf/emf u otros formatos no soportados por la API
                data = z.read(name)
                imagenes.append((base64.b64encode(data).decode(), media_type))
                if len(imagenes) >= max_imagenes:
                    break
    except Exception:
        pass
    return imagenes


# ---------------------------------------------------------------------------
# LLAMADA A LA API
# ---------------------------------------------------------------------------

def _obtener_api_key() -> str | None:
    """
    Busca la API key de Anthropic primero en variables de entorno
    (ANTHROPIC_API_KEY) y, si no está, en st.secrets (Streamlit Cloud).
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


def _llamar_api_vision(imagen_b64: str, contexto_texto: str, tipo_doc: str, media_type: str = "image/png") -> dict:
    """
    Llama a Claude con la imagen de la página y el texto extraído del documento.
    Retorna un dict con hallazgos.
    """
    import urllib.request

    api_key = _obtener_api_key()
    if not api_key:
        return {
            "tipo_imagen": "error",
            "descripcion": (
                "Falta configurar ANTHROPIC_API_KEY (variable de entorno o "
                "st.secrets en Streamlit Cloud) — sin esto el análisis visual "
                "nunca se ejecuta."
            ),
            "coincide_con_texto": None,
            "inconsistencias": [],
            "municipio_visible": None,
            "departamento_visible": None,
            "confianza": "baja"
        }

    prompt = f"""Eres un auditor de documentos ambientales colombianos para proyectos de energía solar (minigranjas fotovoltaicas).

Tipo de documento: {tipo_doc}

Texto extraído del documento (puede tener errores de OCR):
---
{contexto_texto[:3000]}
---

Analiza la imagen de esta página del documento y verifica:

1. **Si hay un MAPA o PLANO**: ¿El municipio, vereda, departamento o coordenadas visibles en el mapa coinciden con lo mencionado en el texto?
2. **Si hay una TABLA de costos o especies**: ¿Los valores o nombres en la tabla coinciden con lo que dice el texto?
3. **Si hay una FOTO de árbol o zona**: ¿Describe brevemente qué muestra (especie, estado, contexto)?
4. **Cualquier inconsistencia visual** entre lo que muestra la imagen y lo que dice el texto.

Responde SOLO con JSON sin backticks, con esta estructura exacta:
{{
  "tipo_imagen": "mapa|tabla|foto|diagrama|otro",
  "descripcion": "descripción breve de la imagen",
  "coincide_con_texto": true|false|null,
  "inconsistencias": ["lista de inconsistencias encontradas, vacía si no hay"],
  "municipio_visible": "nombre si se ve en el mapa, null si no",
  "departamento_visible": "nombre si se ve en el mapa, null si no",
  "confianza": "alta|media|baja"
}}"""

    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 1000,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": imagen_b64
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": api_key,
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            texto_respuesta = data["content"][0]["text"].strip()
            # Limpiar posibles backticks
            texto_respuesta = re.sub(r"```json|```", "", texto_respuesta).strip()
            return json.loads(texto_respuesta)
    except Exception as e:
        return {
            "tipo_imagen": "error",
            "descripcion": f"No se pudo analizar: {e}",
            "coincide_con_texto": None,
            "inconsistencias": [],
            "municipio_visible": None,
            "departamento_visible": None,
            "confianza": "baja"
        }


# ---------------------------------------------------------------------------
# FUNCIÓN PRINCIPAL
# ---------------------------------------------------------------------------

def verificar_imagenes_pdf(
    pdf_bytes: bytes,
    texto_extraido: str,
    tipo_doc: str,
    max_paginas: int = 5
) -> list[dict]:
    """
    Analiza las páginas con imágenes de un PDF y retorna hallazgos visuales.
    Si el archivo no es un PDF real (ej: DOCX), delega a la extracción de
    imágenes embebidas de DOCX en vez de fallar.
    """
    # Verificar header PDF
    if not pdf_bytes[:4] == b'%PDF' and not pdf_bytes[:5] == b'%PDF-':
        # Si tiene header ZIP (PK), es un DOCX -> analizar imágenes embebidas
        if pdf_bytes[:2] == b'PK':
            return _analizar_imagenes_docx(pdf_bytes, texto_extraido, tipo_doc, max_paginas)
        return [{
            "pagina": 0,
            "tipo_imagen": "formato_no_soportado",
            "descripcion": "El análisis visual solo soporta PDF y DOCX.",
            "coincide_con_texto": None,
            "inconsistencias": [],
            "municipio_visible": None,
            "departamento_visible": None,
            "confianza": "baja"
        }]

    try:
        paginas = _paginas_con_imagenes(pdf_bytes)
    except Exception:
        return []

    if not paginas:
        return []

    paginas = paginas[:max_paginas]

    hallazgos = []
    for idx in paginas:
        img_b64 = _rasterizar_pagina(pdf_bytes, idx)
        if not img_b64:
            hallazgos.append({
                "pagina": idx + 1,
                "tipo_imagen": "no_rasterizable",
                "descripcion": "PyMuPDF no disponible — instala pymupdf para análisis visual.",
                "coincide_con_texto": None,
                "inconsistencias": [],
                "municipio_visible": None,
                "departamento_visible": None,
                "confianza": "baja"
            })
            continue

        resultado = _llamar_api_vision(img_b64, texto_extraido, tipo_doc)
        resultado["pagina"] = idx + 1
        hallazgos.append(resultado)

    return hallazgos


def _analizar_imagenes_docx(
    docx_bytes: bytes,
    texto_extraido: str,
    tipo_doc: str,
    max_imagenes: int = 5
) -> list[dict]:
    """Extrae y analiza las imágenes embebidas (mapas, fotos, planos) de un DOCX."""
    imagenes = _extraer_imagenes_docx(docx_bytes, max_imagenes)
    if not imagenes:
        return []

    hallazgos = []
    for i, (img_b64, media_type) in enumerate(imagenes):
        resultado = _llamar_api_vision(img_b64, texto_extraido, tipo_doc, media_type)
        resultado["pagina"] = i + 1
        hallazgos.append(resultado)
    return hallazgos


def verificar_imagenes_documento(
    doc_bytes: bytes,
    texto_extraido: str,
    tipo_doc: str,
    nombre_archivo: str = "",
    max_paginas: int = 5
) -> list[dict]:
    """
    Punto de entrada único: decide por extensión si rasterizar PDF o
    extraer imágenes embebidas de DOCX, y analiza cada una con la API de visión.
    """
    ext = nombre_archivo.lower().rsplit(".", 1)[-1] if "." in nombre_archivo else ""
    if ext in ("docx", "doc") or (not ext and doc_bytes[:2] == b'PK'):
        return _analizar_imagenes_docx(doc_bytes, texto_extraido, tipo_doc, max_paginas)
    return verificar_imagenes_pdf(doc_bytes, texto_extraido, tipo_doc, max_paginas)
