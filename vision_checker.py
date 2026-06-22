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
# LLAMADA A LA API
# ---------------------------------------------------------------------------

def _llamar_api_vision(imagen_b64: str, contexto_texto: str, tipo_doc: str) -> dict:
    """
    Llama a Claude con la imagen de la página y el texto extraído del documento.
    Retorna un dict con hallazgos.
    """
    import urllib.request

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
                        "media_type": "image/png",
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
    Si el archivo no es un PDF real (ej: DOCX), retorna lista vacía con aviso.
    """
    # Verificar header PDF
    if not pdf_bytes[:4] == b'%PDF' and not pdf_bytes[:5] == b'%PDF-':
        # Puede ser DOCX (header PK) u otro formato
        return [{
            "pagina": 0,
            "tipo_imagen": "no_pdf",
            "descripcion": "El archivo no es un PDF — el análisis visual de imágenes solo funciona con PDFs.",
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
