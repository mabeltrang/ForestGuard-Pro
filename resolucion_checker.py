# -*- coding: utf-8 -*-
"""
resolucion_checker.py — Revisión de resoluciones de aprovechamiento forestal
(actos administrativos de las CAR).

Las resoluciones llegan como escaneos con una capa de OCR muy sucia, así que
la extracción combina el texto OCR (para ubicar páginas) con las imágenes de
cada página (para leer tablas y cifras), usando la misma API de visión que
document_vision.py. Sobre los datos extraídos se corren verificaciones
deterministas: días calendario/hábiles desde el radicado, tramo de comisión,
titular, totales, compensación por especie, diferencias de DAP y valores que
cambian dentro del mismo documento (errores de copia de otra resolución).
"""

import base64
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Optional

from document_vision import _llamar_vision_json


# ---------------------------------------------------------------------------
# CONSTANTES
# ---------------------------------------------------------------------------

class Severidad(str, Enum):
    ERROR = "error"
    ALERTA = "alerta"
    INFO = "info"


@dataclass(frozen=True)
class TramoComision:
    dias_min: int
    dias_max: int
    valor: int


TRAMOS_COMISION_DEFECTO: tuple = (
    TramoComision(0, 90, 500_000),
    TramoComision(91, 180, 250_000),
)

TOLERANCIA_DIAS_DEFECTO = 10
UMBRAL_DIFERENCIA_DAP = 0.30
MAX_PAGINAS = 20
DPI_PAGINAS = 110
JPEG_CALIDAD = 70
MAX_CARACTERES_OCR = 60_000
TIMEOUT_API = 180
MAX_TOKENS_RESPUESTA = 8000


@dataclass
class Hallazgo:
    severidad: Severidad
    titulo: str
    detalle: str


# ---------------------------------------------------------------------------
# FESTIVOS Y DÍAS HÁBILES (Colombia, Ley 51 de 1983)
# ---------------------------------------------------------------------------

def _domingo_pascua(anio: int) -> date:
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)


def _siguiente_lunes(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7)


def festivos_colombia(anio: int) -> set:
    fijos = {date(anio, 1, 1), date(anio, 5, 1), date(anio, 7, 20),
             date(anio, 8, 7), date(anio, 12, 8), date(anio, 12, 25)}
    trasladables = {_siguiente_lunes(date(anio, m, d)) for m, d in
                    ((1, 6), (3, 19), (6, 29), (8, 15), (10, 12), (11, 1), (11, 11))}
    pascua = _domingo_pascua(anio)
    semana_santa = {pascua - timedelta(days=3), pascua - timedelta(days=2)}
    moviles = {pascua + timedelta(days=n) for n in (43, 64, 71)}
    return fijos | trasladables | semana_santa | moviles


def contar_dias(inicio: date, fin: date) -> tuple:
    """Días calendario y hábiles transcurridos entre dos fechas (sin contar
    el día de inicio). Devuelve (calendario, habiles, festivos_en_el_periodo)."""
    if fin < inicio:
        return (0, 0, [])
    festivos = set()
    for anio in range(inicio.year, fin.year + 1):
        festivos |= festivos_colombia(anio)
    habiles = 0
    festivos_periodo = []
    d = inicio + timedelta(days=1)
    while d <= fin:
        if d in festivos and d.weekday() < 5:
            festivos_periodo.append(d)
        elif d.weekday() < 5:
            habiles += 1
        d += timedelta(days=1)
    return ((fin - inicio).days, habiles, festivos_periodo)


def tramo_comision(dias: int, tramos: tuple = TRAMOS_COMISION_DEFECTO,
                   tolerancia: int = 0) -> Optional[TramoComision]:
    """Primer tramo (en orden) cuyo límite superior, más la tolerancia,
    cubre los días. Con tolerancia 10, un permiso de 97 días sigue pagando
    el tramo de 0-90."""
    for t in sorted(tramos, key=lambda x: x.dias_max):
        if dias <= t.dias_max + tolerancia:
            return t
    return None


# ---------------------------------------------------------------------------
# EXTRACCIÓN
# ---------------------------------------------------------------------------

def _paginas_pdf(pdf_bytes: bytes) -> tuple:
    """Devuelve (texto OCR con marcas de página, lista de imágenes JPEG b64)."""
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    textos, imagenes = [], []
    matriz = fitz.Matrix(DPI_PAGINAS / 72, DPI_PAGINAS / 72)
    for i, page in enumerate(doc):
        if i >= MAX_PAGINAS:
            break
        textos.append(f"=== PÁGINA {i + 1} ===\n{page.get_text()}")
        pix = page.get_pixmap(matrix=matriz, alpha=False)
        imagenes.append((base64.b64encode(pix.tobytes("jpeg", jpg_quality=JPEG_CALIDAD)).decode(), "image/jpeg"))
    doc.close()
    return ("\n".join(textos)[:MAX_CARACTERES_OCR], imagenes)


_PROMPT = """Estás viendo una resolución de una Corporación Autónoma Regional \
(Colombia) que autoriza (o niega) un aprovechamiento forestal de árboles \
aislados. Tienes las imágenes de cada página en orden y, abajo, el texto OCR \
(sucio) con marcas "=== PÁGINA n ===" para ubicar páginas. Usa las imágenes \
como fuente principal para cifras y tablas.

Extrae los datos y responde SOLO con JSON sin backticks, con esta forma \
(usa null si no aparece; fechas en formato AAAA-MM-DD; números con punto \
decimal):

{
 "resolucion": {"numero": str, "fecha": str, "autoridad": str, "sede": str, "sentido": "autoriza" | "niega" | "otro"},
 "proyecto": str,
 "radicado": {"numero": str, "fecha": str},
 "expediente": str,
 "auto_inicio": {"numero": str, "fecha": str},
 "concepto_tecnico": {"numero": str, "fecha": str},
 "solicitante": {"empresa": str, "nit": str, "representante_legal": str, "cedula_representante": str, "calidad": str},
 "titular_autorizado": {"nombre": str, "cedula": str, "calidad": str},
 "predio": {"nombre": str, "vereda": str, "municipio": str, "departamento": str, "matricula": str, "area_predio_ha": number, "area_intervencion_ha": number},
 "especies": [{"nombre_comun": str, "nombre_cientifico": str, "arboles": int, "volumen_m3": number, "categoria_amenaza": str | null}],
 "total_arboles": int,
 "volumen_total_m3": number,
 "intensidad_muestreo_pct": number,
 "verificacion_dap": [{"id": str, "especie": str, "dap_cas_m": number, "dap_solicitante_m": number}],
 "compensacion": {
   "grupos": [{"descripcion": str, "relacion": int, "arboles_talados": int, "arboles_a_reponer": int}],
   "total_arboles_a_reponer": int,
   "lugar": str,
   "mantenimiento": str,
   "informe": str
 },
 "objeto_aprovechamiento": str,
 "plazo_ejecucion": str,
 "recurso": str,
 "cobra_tarifa_seguimiento": bool,
 "ordena_publicacion": bool,
 "detalle_publicacion": str | null,
 "consignaciones": [{"valor": number, "fecha": str, "concepto": str}],
 "correo_notificacion": str,
 "obligaciones": [str],
 "menciones": {
   "predios": [{"valor": str, "pagina": int}],
   "matriculas": [{"valor": str, "pagina": int, "contexto": str}],
   "municipios": [{"valor": str, "pagina": int}],
   "cedulas": [{"persona": str, "valor": str, "pagina": int}]
 },
 "inconsistencias_internas": [{"pagina": int, "descripcion": str}]
}

Instrucciones:
- "relacion" es el número de árboles a sembrar por cada árbol talado (1:4 → 4).
- En "menciones" lista CADA vez que aparece un nombre de predio, una matrícula \
inmobiliaria, un municipio del predio o una cédula asociada a una persona, \
tal como está escrito, con su página. No las unifiques: el objetivo es \
detectar cuando el documento cambia de valor (errores de copia).
- En "inconsistencias_internas" anota contradicciones dentro del documento: \
áreas, cantidades, rangos de DAP, nombres o cédulas que no cuadran, datos que \
parecen copiados de otro proyecto, texto en número que no coincide con la \
cifra, etc. Sé concreto y cita la página.
- "obligaciones": frases cortas con lo que la resolución exige al titular.

TEXTO OCR:
"""


def extraer_resolucion(pdf_bytes: bytes) -> dict:
    texto, imagenes = _paginas_pdf(pdf_bytes)
    return _llamar_vision_json(imagenes, _PROMPT + texto,
                               max_tokens=MAX_TOKENS_RESPUESTA, timeout=TIMEOUT_API)


# ---------------------------------------------------------------------------
# VERIFICACIONES
# ---------------------------------------------------------------------------

def _fecha(valor: object) -> Optional[date]:
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def _num(valor: object) -> Optional[float]:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _normalizar(texto: object) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _solo_digitos(texto: object) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def _valores_distintos(menciones: list, clave=_normalizar) -> dict:
    grupos = {}
    for m in menciones or []:
        if not isinstance(m, dict) or not m.get("valor"):
            continue
        k = clave(m["valor"])
        if k:
            grupos.setdefault(k, []).append(m)
    return grupos


def verificar_titular(datos: dict, empresa: str = "UNERGY") -> list:
    titular = (datos.get("titular_autorizado") or {}).get("nombre") or ""
    if not titular:
        return [Hallazgo(Severidad.ALERTA, "Titular no identificado",
                         "No se pudo leer a nombre de quién quedó la autorización.")]
    if empresa.lower() in titular.lower():
        return [Hallazgo(Severidad.INFO, "Autorización a nombre de la empresa", titular)]
    return [Hallazgo(
        Severidad.ALERTA, "Autorización a nombre del propietario, no de la empresa",
        f"Titular: {titular}. La compensación, los informes y los salvoconductos quedan "
        "en cabeza del propietario y la autorización no se puede ceder sin permiso "
        "escrito de la autoridad.")]


def verificar_totales(datos: dict) -> list:
    especies = [e for e in datos.get("especies") or [] if isinstance(e, dict)]
    if not especies:
        return []
    hallazgos = []
    suma_arboles = sum(int(_num(e.get("arboles")) or 0) for e in especies)
    total = _num(datos.get("total_arboles"))
    if total is not None and int(total) != suma_arboles:
        hallazgos.append(Hallazgo(Severidad.ERROR, "Total de árboles no cuadra",
                                  f"Suma por especie: {suma_arboles} · total reportado: {int(total)}"))
    suma_vol = round(sum(_num(e.get("volumen_m3")) or 0 for e in especies), 2)
    vol = _num(datos.get("volumen_total_m3"))
    if vol is not None and abs(vol - suma_vol) > 0.015:
        hallazgos.append(Hallazgo(Severidad.ERROR, "Volumen total no cuadra",
                                  f"Suma por especie: {suma_vol} m³ · total reportado: {vol} m³"))
    return hallazgos


def verificar_compensacion(datos: dict) -> list:
    comp = datos.get("compensacion") or {}
    grupos = [g for g in comp.get("grupos") or [] if isinstance(g, dict)]
    hallazgos = []
    if not grupos:
        return [Hallazgo(Severidad.ALERTA, "Compensación no identificada",
                         "No se encontró la tabla de reposición de árboles.")]
    calculado = 0
    for g in grupos:
        rel, talados = _num(g.get("relacion")), _num(g.get("arboles_talados"))
        reponer = _num(g.get("arboles_a_reponer"))
        if rel is None or talados is None:
            continue
        esperado = int(rel * talados)
        calculado += esperado
        if reponer is not None and int(reponer) != esperado:
            hallazgos.append(Hallazgo(
                Severidad.ERROR, f"Reposición mal calculada ({g.get('descripcion')})",
                f"{int(talados)} × {int(rel)} = {esperado}, pero dice {int(reponer)}"))
    total = _num(comp.get("total_arboles_a_reponer"))
    if total is not None and calculado and int(total) != calculado:
        hallazgos.append(Hallazgo(Severidad.ERROR, "Total de reposición no cuadra",
                                  f"Calculado: {calculado} · reportado: {int(total)}"))
    talados_comp = sum(int(_num(g.get("arboles_talados")) or 0) for g in grupos)
    total_arboles = _num(datos.get("total_arboles"))
    if total_arboles is not None and talados_comp and talados_comp != int(total_arboles):
        hallazgos.append(Hallazgo(
            Severidad.ALERTA, "Árboles compensados ≠ árboles autorizados",
            f"La compensación cubre {talados_comp} árboles y se autorizan {int(total_arboles)}."))
    amenazadas = [e for e in datos.get("especies") or []
                  if isinstance(e, dict) and e.get("categoria_amenaza")]
    for e in amenazadas:
        hallazgos.append(Hallazgo(
            Severidad.ALERTA, f"Especie amenazada: {e.get('nombre_cientifico') or e.get('nombre_comun')}",
            f"Categoría {e.get('categoria_amenaza')} · {e.get('arboles')} árbol(es). "
            "Verifica que tenga relación de compensación diferenciada."))
    return hallazgos


def verificar_dap(datos: dict, umbral: float = UMBRAL_DIFERENCIA_DAP) -> list:
    hallazgos = []
    for v in datos.get("verificacion_dap") or []:
        if not isinstance(v, dict):
            continue
        cas, sol = _num(v.get("dap_cas_m")), _num(v.get("dap_solicitante_m"))
        if not cas or not sol:
            continue
        dif = abs(cas - sol) / sol
        if dif > umbral:
            hallazgos.append(Hallazgo(
                Severidad.ALERTA, f"DAP muy distinto: árbol {v.get('id')} ({v.get('especie')})",
                f"Autoridad: {cas} m · inventario: {sol} m ({dif:.0%} de diferencia). "
                "Revisa ese registro del inventario."))
    return hallazgos


def verificar_menciones(datos: dict) -> list:
    menciones = datos.get("menciones") or {}
    hallazgos = []
    reglas = (
        ("predios", "el nombre del predio", _normalizar),
        ("municipios", "el municipio", _normalizar),
        ("matriculas", "la matrícula", _solo_digitos),
    )
    for clave, etiqueta, normalizador in reglas:
        grupos = _valores_distintos(menciones.get(clave), normalizador)
        if len(grupos) > 1:
            detalle = " · ".join(
                f"«{ms[0]['valor']}» (pág. {', '.join(str(m.get('pagina')) for m in ms)})"
                + (f" — {ms[0]['contexto']}" if ms[0].get("contexto") else "")
                for ms in grupos.values())
            hallazgos.append(Hallazgo(Severidad.ERROR, f"Cambia {etiqueta} dentro del documento", detalle))

    por_persona = {}
    for c in menciones.get("cedulas") or []:
        if isinstance(c, dict) and c.get("valor"):
            por_persona.setdefault(_normalizar(c.get("persona"))[:12], []).append(c)
    for ms in por_persona.values():
        valores = {_solo_digitos(m["valor"]) for m in ms if _solo_digitos(m["valor"])}
        if len(valores) > 1:
            hallazgos.append(Hallazgo(
                Severidad.ERROR, f"Cédula distinta para {ms[0].get('persona')}",
                " · ".join(f"{m['valor']} (pág. {m.get('pagina')})" for m in ms)))
    por_cedula = {}
    for c in menciones.get("cedulas") or []:
        if isinstance(c, dict) and _solo_digitos(c.get("valor")):
            por_cedula.setdefault(_solo_digitos(c["valor"]), set()).add(_normalizar(c.get("persona"))[:12])
    for ced, personas in por_cedula.items():
        if len(personas) > 1:
            hallazgos.append(Hallazgo(Severidad.ERROR, "Una cédula aparece asignada a dos personas",
                                      f"Cédula {ced}"))
    return hallazgos


def verificar_inconsistencias_ia(datos: dict) -> list:
    return [Hallazgo(Severidad.ALERTA, f"Pág. {i.get('pagina')}", i.get("descripcion", ""))
            for i in datos.get("inconsistencias_internas") or []
            if isinstance(i, dict) and i.get("descripcion")]


def verificar_pagos_y_publicacion(datos: dict) -> list:
    hallazgos = []
    if datos.get("ordena_publicacion"):
        hallazgos.append(Hallazgo(Severidad.ALERTA, "Ordena publicación",
                                  datos.get("detalle_publicacion") or "Revisa el artículo correspondiente."))
    if datos.get("cobra_tarifa_seguimiento"):
        hallazgos.append(Hallazgo(Severidad.INFO, "Cobra tarifa de seguimiento",
                                  "El monto no viene en la resolución; la autoridad lo liquida después."))
    return hallazgos


def revisar(datos: dict, empresa: str = "UNERGY") -> list:
    return (verificar_titular(datos, empresa) + verificar_menciones(datos)
            + verificar_totales(datos) + verificar_compensacion(datos)
            + verificar_dap(datos) + verificar_inconsistencias_ia(datos)
            + verificar_pagos_y_publicacion(datos))


def fechas_clave(datos: dict) -> tuple:
    """(fecha_radicado, fecha_resolucion) como date o None."""
    return (_fecha((datos.get("radicado") or {}).get("fecha")),
            _fecha((datos.get("resolucion") or {}).get("fecha")))
