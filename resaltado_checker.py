"""
resaltado_checker.py — Detección de resaltado AMARILLO en documentos.

En Unergy el resaltado amarillo se usa como convención interna para marcar
texto o zonas de una imagen/plano donde falta un dato antes de radicar. Este
módulo detecta:

1. Texto resaltado en amarillo dentro de párrafos y tablas de un .docx
   (incluyendo cuadros de texto flotantes), leyendo el atributo nativo de
   resaltado de Word (w:highlight val="yellow"), NO un color de fuente.
2. Zonas amarillas dentro de imágenes embebidas (docx) o páginas rasterizadas
   (pdf) — por ejemplo un pantallazo de un plano con un círculo o resaltador
   amarillo dibujado encima — usando un análisis de píxeles por rango de color.
3. Anotaciones de tipo "Highlight" nativas de PDF (cuando el resaltado se hizo
   con la herramienta de resaltado del lector de PDF, no dibujado a mano).

No requiere API externa: todo es análisis local (python-docx / pypdf / PyMuPDF
+ Pillow). Si PyMuPDF no está instalado, el análisis de imágenes de PDF se
omite silenciosamente y solo se reportan las anotaciones nativas.
"""

import io
import zipfile
from typing import Optional

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from pypdf import PdfReader

try:
    from PIL import Image
    import numpy as np
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

try:
    import fitz  # PyMuPDF
    _FITZ_OK = True
except ImportError:
    _FITZ_OK = False


# ---------------------------------------------------------------------------
# UTILIDAD: % de píxeles "amarillo resaltador" en una imagen
# ---------------------------------------------------------------------------

def _porcentaje_pixeles_amarillos(imagen_bytes: bytes) -> Optional[float]:
    """
    Retorna el % de píxeles cuyo tono cae en el rango de amarillo de
    resaltador (no amarillo de cualquier objeto, sino el tono brillante y
    saturado típico de un marcador/highlighter: H≈45-65°, S y V altos).

    None si la imagen no se pudo abrir o Pillow/numpy no están disponibles.
    """
    if not _PIL_OK:
        return None
    try:
        img = Image.open(io.BytesIO(imagen_bytes)).convert("RGB")
        # Reducir tamaño para que el escaneo sea rápido en imágenes grandes
        img.thumbnail((400, 400))
        arr = np.asarray(img).astype("float32") / 255.0
        r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]

        maxc = np.max(arr, axis=-1)
        minc = np.min(arr, axis=-1)
        delta = maxc - minc

        with np.errstate(divide="ignore", invalid="ignore"):
            hue = np.zeros_like(maxc)
            mask = delta > 1e-6
            # Hue en grados, solo donde el máximo es el canal rojo o verde
            # (el amarillo siempre cae en esa franja, nunca donde domina azul)
            idx_r = mask & (maxc == r)
            idx_g = mask & (maxc == g) & ~idx_r
            hue[idx_r] = (60 * ((g[idx_r] - b[idx_r]) / delta[idx_r]) + 360) % 360
            hue[idx_g] = 60 * ((b[idx_g] - r[idx_g]) / delta[idx_g]) + 120

        sat = np.where(maxc > 0, delta / np.maximum(maxc, 1e-6), 0)
        val = maxc

        amarillo = (
            (hue >= 45) & (hue <= 68) &
            (sat >= 0.35) &
            (val >= 0.55)
        )
        return float(100.0 * amarillo.sum() / amarillo.size)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# DOCX — texto resaltado (nativo de Word)
# ---------------------------------------------------------------------------

def _runs_resaltados_amarillo(paragraph, contexto: str) -> list[dict]:
    hallazgos = []
    fragmento_actual = ""
    for run in paragraph.runs:
        if run.font.highlight_color == WD_COLOR_INDEX.YELLOW and run.text.strip():
            fragmento_actual += run.text
        else:
            if fragmento_actual.strip():
                hallazgos.append({
                    "texto_resaltado": fragmento_actual.strip(),
                    "contexto": contexto[:160],
                })
            fragmento_actual = ""
    if fragmento_actual.strip():
        hallazgos.append({
            "texto_resaltado": fragmento_actual.strip(),
            "contexto": contexto[:160],
        })
    return hallazgos


_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_MC_CHOICE = f"{{{_MC_NS}}}Choice"


def _procesar_tabla(table, hallazgos: list) -> None:
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for h in _runs_resaltados_amarillo(p, p.text):
                    h["ubicacion"] = "tabla"
                    hallazgos.append(h)


def _procesar_textboxes(element, doc, hallazgos: list) -> None:
    """
    Recorre cuadros de texto (<w:txbxContent>) anidados en `element` y revisa
    el resaltado de sus párrafos/tablas. Solo procesa la copia moderna
    (<mc:Choice>) para no duplicar hallazgos con la copia legada VML.
    """
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from docx.table import Table

    def _revisar_txbx(txbx):
        for sub in txbx:
            subtag = sub.tag.split("}")[-1] if "}" in sub.tag else sub.tag
            if subtag == "p":
                p = Paragraph(sub, doc)
                for h in _runs_resaltados_amarillo(p, p.text):
                    h["ubicacion"] = "cuadro de texto"
                    hallazgos.append(h)
            elif subtag == "tbl":
                _procesar_tabla(Table(sub, doc), hallazgos)

    choices = list(element.iter(_MC_CHOICE))
    if choices:
        for choice in choices:
            for txbx in choice.iter(qn("w:txbxContent")):
                _revisar_txbx(txbx)
    else:
        for txbx in element.iter(qn("w:txbxContent")):
            _revisar_txbx(txbx)


def detectar_resaltado_texto_docx(file_path: str) -> list:
    """
    Recorre párrafos, tablas y cuadros de texto flotantes en el orden real
    del documento y retorna cada tramo de texto marcado con resaltado
    AMARILLO nativo de Word (w:highlight val="yellow"), no color de fuente.

    Retorna lista de {"texto_resaltado": str, "contexto": str, "ubicacion": str}.
    """
    from docx.text.paragraph import Paragraph
    from docx.table import Table

    doc = Document(file_path)
    hallazgos: list = []
    body = doc.element.body

    for child in body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            p = Paragraph(child, doc)
            for h in _runs_resaltados_amarillo(p, p.text):
                h["ubicacion"] = "párrafo"
                hallazgos.append(h)
            _procesar_textboxes(child, doc, hallazgos)

        elif tag == "tbl":
            _procesar_tabla(Table(child, doc), hallazgos)
            _procesar_textboxes(child, doc, hallazgos)

    # Encabezados y pies de página también pueden llevar resaltado (ej. un
    # dato pendiente en el pie con la fecha/radicado)
    for section in doc.sections:
        for contenedor, etiqueta in (
            (section.header, "encabezado"),
            (section.footer, "pie de página"),
        ):
            for p in contenedor.paragraphs:
                for h in _runs_resaltados_amarillo(p, p.text):
                    h["ubicacion"] = etiqueta
                    hallazgos.append(h)
            for table in contenedor.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            for h in _runs_resaltados_amarillo(p, p.text):
                                h["ubicacion"] = etiqueta
                                hallazgos.append(h)

    return hallazgos


# ---------------------------------------------------------------------------
# DOCX — imágenes embebidas con zonas amarillas
# ---------------------------------------------------------------------------

def detectar_resaltado_imagenes_docx(file_path: str, umbral_pct: float = 0.8) -> list[dict]:
    """
    Extrae las imágenes embebidas (word/media/) y marca las que tengan un %
    de píxeles "amarillo resaltador" por encima de `umbral_pct`.

    Retorna lista de {"archivo_imagen": str, "pct_amarillo": float}.
    """
    hallazgos = []
    if not _PIL_OK:
        return hallazgos
    try:
        with zipfile.ZipFile(file_path) as z:
            media_files = sorted(n for n in z.namelist() if n.startswith("word/media/"))
            for name in media_files:
                ext = name.rsplit(".", 1)[-1].lower()
                if ext not in ("png", "jpg", "jpeg", "bmp", "gif"):
                    continue  # wmf/emf no son legibles por Pillow
                pct = _porcentaje_pixeles_amarillos(z.read(name))
                if pct is not None and pct >= umbral_pct:
                    hallazgos.append({
                        "archivo_imagen": name.rsplit("/", 1)[-1],
                        "pct_amarillo": round(pct, 2),
                    })
    except Exception:
        pass
    return hallazgos


# ---------------------------------------------------------------------------
# PDF — anotaciones de resaltado nativas
# ---------------------------------------------------------------------------

def detectar_resaltado_anotaciones_pdf(file_path: str) -> list[dict]:
    """
    Busca anotaciones tipo Highlight (subrayado de lector de PDF) en cada
    página. Retorna lista de {"pagina": int, "comentario": str|None}.
    """
    hallazgos = []
    try:
        reader = PdfReader(file_path)
        for i, page in enumerate(reader.pages):
            annots = page.get("/Annots")
            if not annots:
                continue
            for ref in annots:
                try:
                    obj = ref.get_object()
                except Exception:
                    continue
                if obj.get("/Subtype") == "/Highlight":
                    color = obj.get("/C")  # componentes de color [r,g,b] 0-1
                    es_amarillo = True
                    if color and len(color) == 3:
                        r, g, b = [float(c) for c in color]
                        es_amarillo = r > 0.7 and g > 0.7 and b < 0.5
                    if es_amarillo:
                        hallazgos.append({
                            "pagina": i + 1,
                            "comentario": str(obj.get("/Contents")) if obj.get("/Contents") else None,
                        })
    except Exception:
        pass
    return hallazgos


# ---------------------------------------------------------------------------
# PDF — zonas amarillas en páginas rasterizadas (marcas hechas a mano/imagen)
# ---------------------------------------------------------------------------

def detectar_resaltado_imagenes_pdf(file_path: str, umbral_pct: float = 0.6, max_paginas: int = 30) -> list[dict]:
    """
    Rasteriza cada página (requiere PyMuPDF) y marca aquellas con un % de
    píxeles amarillos por encima de `umbral_pct`. Útil para resaltados hechos
    en un editor de imágenes o en escaneos, no solo con la herramienta nativa
    de resaltado de un lector de PDF.
    """
    hallazgos = []
    if not _FITZ_OK or not _PIL_OK:
        return hallazgos
    try:
        doc = fitz.open(file_path)
        for i in range(min(len(doc), max_paginas)):
            page = doc[i]
            mat = fitz.Matrix(100 / 72, 100 / 72)  # 100 dpi, suficiente para color
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pct = _porcentaje_pixeles_amarillos(pix.tobytes("png"))
            if pct is not None and pct >= umbral_pct:
                hallazgos.append({"pagina": i + 1, "pct_amarillo": round(pct, 2)})
        doc.close()
    except Exception:
        pass
    return hallazgos


# ---------------------------------------------------------------------------
# PUNTO DE ENTRADA ÚNICO
# ---------------------------------------------------------------------------

def detectar_resaltado_documento(file_path: str, nombre_archivo: str = "") -> dict:
    """
    Dispatcher por extensión. Retorna:
    {
        "texto": [...],            # tramos de texto resaltados en amarillo (solo docx)
        "imagenes": [...],         # imágenes/páginas con zonas amarillas
        "anotaciones_pdf": [...],  # anotaciones nativas de resaltado (solo pdf)
        "tiene_hallazgos": bool,
    }
    """
    nombre = nombre_archivo or file_path
    ext = nombre.lower().rsplit(".", 1)[-1] if "." in nombre else ""

    resultado = {"texto": [], "imagenes": [], "anotaciones_pdf": [], "tiene_hallazgos": False}

    if ext in ("docx", "doc"):
        try:
            resultado["texto"] = detectar_resaltado_texto_docx(file_path)
        except Exception:
            resultado["texto"] = []
        resultado["imagenes"] = detectar_resaltado_imagenes_docx(file_path)

    elif ext == "pdf":
        resultado["anotaciones_pdf"] = detectar_resaltado_anotaciones_pdf(file_path)
        resultado["imagenes"] = detectar_resaltado_imagenes_pdf(file_path)

    resultado["tiene_hallazgos"] = bool(
        resultado["texto"] or resultado["imagenes"] or resultado["anotaciones_pdf"]
    )
    return resultado
