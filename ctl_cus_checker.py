# -*- coding: utf-8 -*-
"""
ctl_cus_checker.py — Cruce de CTL (Certificado de Tradición y Libertad de
Matrícula Inmobiliaria) y CUS (Certificado de Uso del Suelo) para proyectos
con uno o varios predios.

Qué hace:
  1. Extrae el/los número(s) de matrícula inmobiliaria mencionados en cada
     archivo CTL y en cada archivo CUS.
  2. Cruza los conjuntos de matrículas entre CTL y CUS: qué matrícula tiene
     CTL pero le falta CUS, cuál tiene CUS pero le falta CTL, y cuáles
     tienen ambos (caso normal en proyectos multi-predio, ej. COLCEST757
     con matrículas 190-108790 y 190-112462).
  3. Extrae el/los titular(es) de derechos reales de dominio del CTL
     (nombre + tipo/número de identificación) y los compara contra el
     propietario que la app ya identificó en el Informe AF / Inventario
     (mismo criterio de similitud que propietario_checker.py).
  4. Extrae, de forma informativa, el texto de "uso del suelo" del CUS
     (uso principal / compatible / restringido), sin comparación estricta
     — es solo para que el usuario lo vea de un vistazo.

Este módulo trabaja sobre TEXTO real extraído del PDF/DOCX (usa
extractor.extract_text_from_file en app.py). Si el CTL o el CUS es un
escaneo sin capa de texto (foto pura), pypdf no podrá leerlo — en ese
caso no hay match y se advierte al usuario, igual que en propietario_checker.py.
Si llegas a necesitar leer CTL/CUS escaneados como imagen, se puede extender
con el mismo enfoque de visión que cedula_checker.py.
"""

import re
import unicodedata
import difflib
from typing import Optional


# ---------------------------------------------------------------------------
# NORMALIZACIÓN / SIMILITUD (mismo criterio que propietario_checker.py)
# ---------------------------------------------------------------------------

def _normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^A-Za-z0-9 ]", " ", texto)
    return " ".join(texto.upper().split())


def _similitud(a: str, b: str) -> float:
    a_norm, b_norm = _normalizar_texto(a), _normalizar_texto(b)
    if not a_norm or not b_norm:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a_norm, b_norm).ratio()
    if a_norm in b_norm or b_norm in a_norm:
        ratio = max(ratio, 0.9)
    return ratio


def _normalizar_matricula(m: str) -> str:
    """
    '190-108.790', '190 108790', '190-108790' -> '190-108790'
    Deja solo dígitos y un guion entre el prefijo de círculo registral y el
    consecutivo, que es el formato estándar colombiano (ej. 190-108790).
    """
    solo_digitos = re.sub(r"[^\d]", "", m)
    if len(solo_digitos) <= 3:
        return solo_digitos
    return f"{solo_digitos[:3]}-{solo_digitos[3:]}"


# ---------------------------------------------------------------------------
# EXTRACCIÓN — MATRÍCULA INMOBILIARIA (de CTL o de CUS)
# ---------------------------------------------------------------------------

_PATRON_MATRICULA = re.compile(
    r"matr[ií]cula(?:s)?\s+inmobiliaria(?:s)?\s*(?:n[uú]mero|no\.?|n[°º])?\s*[:\-]?\s*"
    r"(\d{2,4}\s*-\s*\d{3,10})",
    re.IGNORECASE,
)

# Fallback: formato suelto "190-108790" sin la palabra "matrícula" pegada
# justo antes (ej. cuando aparece en un encabezado/tabla separado del rótulo).
_PATRON_MATRICULA_SUELTA = re.compile(r"\b(\d{3}-\d{4,8})\b")


def extraer_matriculas(texto: str) -> list:
    """
    Retorna la lista de matrículas inmobiliarias (normalizadas, sin
    duplicados, en orden de aparición) mencionadas en el texto.
    """
    encontradas = []
    vistas = set()

    for m in _PATRON_MATRICULA.finditer(texto):
        norm = _normalizar_matricula(m.group(1))
        if norm and norm not in vistas:
            vistas.add(norm)
            encontradas.append(norm)

    # Solo usar el patrón suelto si el patrón con rótulo no encontró nada,
    # para evitar falsos positivos con otros números tipo "190-1087901234"
    # (radicados, teléfonos, etc.)
    if not encontradas:
        for m in _PATRON_MATRICULA_SUELTA.finditer(texto):
            norm = _normalizar_matricula(m.group(1))
            if norm and norm not in vistas:
                vistas.add(norm)
                encontradas.append(norm)

    return encontradas


# ---------------------------------------------------------------------------
# EXTRACCIÓN — TITULAR(ES) DE DERECHOS REALES DE DOMINIO (CTL)
# ---------------------------------------------------------------------------

# Formato "etiqueta: valor" típico del certificado del SNR/VUR:
#   Nombre           : GARCIA PEREZ MARIA
#   Identificación   : C.C. 12345678
_PATRON_TITULAR_ETIQUETAS = re.compile(
    r"nombre\s*[:\-]?\s*(?P<nombre>[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9&.,\- ]{2,80}?)\s*\n"
    r"[^\n]{0,40}?identificaci[oó]n\s*[:\-]?\s*"
    r"(?P<tipo>C\.?\s?C\.?|C\.?\s?E\.?|NIT)\.?\s*[:\-]?\s*(?P<num>[\d.,\-]+)",
    re.IGNORECASE,
)

# Formato prosa, por si el CTL cita una escritura ("compareciente ... identificado con
# cédula de ciudadanía No. ..."), igual al patrón de propietario_checker.py.
_PATRON_TITULAR_PROSA = re.compile(
    r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9&.\- ]{3,80}?)"
    r"\s*,?\s*identificad[oa]?\s+con\s+"
    r"(C\.?\s?C\.?|NIT|C\.?E\.?|Ced(?:ula)?)\.?\s*([\d.,\-]+)",
    re.IGNORECASE,
)


def extraer_titulares_ctl(texto: str) -> list:
    """
    Retorna [{"nombre","tipo_id","numero_id"}, ...] de los titulares de
    derechos reales de dominio mencionados en el CTL. Intenta primero el
    formato de etiquetas (más confiable en un CTL real), y complementa con
    el patrón de prosa si no encontró nada.
    """
    hallazgos = []
    vistos = set()

    for m in _PATRON_TITULAR_ETIQUETAS.finditer(texto):
        nombre = m.group("nombre").strip(" ,.\n")
        tipo_id = m.group("tipo").replace(" ", "").upper().rstrip(".")
        numero_id = m.group("num")
        clave = (nombre.upper(), numero_id)
        if clave in vistos or not nombre:
            continue
        vistos.add(clave)
        hallazgos.append({"nombre": nombre, "tipo_id": tipo_id, "numero_id": numero_id})

    if not hallazgos:
        # Respaldo en prosa: se normaliza a espacios simples porque un
        # nombre partido en dos líneas por ajuste de línea haría fallar el
        # patrón (a diferencia del patrón de etiquetas de arriba, que SÍ
        # depende de saltos de línea reales entre "Nombre" e "Identificación").
        texto_plano = re.sub(r"\s+", " ", texto)
        for m in _PATRON_TITULAR_PROSA.finditer(texto_plano):
            nombre_raw, tipo_id, numero_id = m.groups()
            nombre = re.sub(
                r"^(la\s+se[ñn]ora|el\s+se[ñn]or(?:\(a\))?|la\s+sociedad)\s+",
                "", nombre_raw, flags=re.IGNORECASE
            ).strip(" ,.")
            clave = (nombre.upper(), numero_id)
            if clave in vistos or not nombre:
                continue
            vistos.add(clave)
            hallazgos.append({
                "nombre": nombre,
                "tipo_id": tipo_id.replace(" ", "").upper().rstrip("."),
                "numero_id": numero_id.strip(" ,."),
            })

    return hallazgos


# ---------------------------------------------------------------------------
# EXTRACCIÓN — USO DEL SUELO (CUS) — informativo, sin comparación estricta
# ---------------------------------------------------------------------------

_PATRON_USO_SUELO = re.compile(
    r"(uso\s+(?:principal|del\s+suelo|permitido|compatible)[^\n]{0,150})",
    re.IGNORECASE,
)


def extraer_uso_suelo(texto: str, max_fragmentos: int = 3) -> list:
    """Retorna fragmentos de texto relacionados con el uso del suelo (informativo)."""
    fragmentos = []
    for m in _PATRON_USO_SUELO.finditer(texto):
        frag = " ".join(m.group(1).split())
        if frag not in fragmentos:
            fragmentos.append(frag)
        if len(fragmentos) >= max_fragmentos:
            break
    return fragmentos


# ---------------------------------------------------------------------------
# CRUCE DE MATRÍCULAS ENTRE CTL Y CUS (faltantes / sobrantes)
# ---------------------------------------------------------------------------

def comparar_matriculas_ctl_cus(matriculas_por_ctl: dict, matriculas_por_cus: dict) -> dict:
    """
    matriculas_por_ctl / matriculas_por_cus: {nombre_archivo: [matriculas...]}

    Retorna:
    {
      "en_ambos": [{"matricula", "archivos_ctl": [...], "archivos_cus": [...]}],
      "solo_ctl":  [{"matricula", "archivos_ctl": [...]}],   # falta CUS
      "solo_cus":  [{"matricula", "archivos_cus": [...]}],   # falta CTL
    }
    """
    mapa_ctl = {}  # matricula -> [archivos]
    for archivo, matriculas in matriculas_por_ctl.items():
        for m in matriculas:
            mapa_ctl.setdefault(m, []).append(archivo)

    mapa_cus = {}
    for archivo, matriculas in matriculas_por_cus.items():
        for m in matriculas:
            mapa_cus.setdefault(m, []).append(archivo)

    todas = sorted(set(mapa_ctl) | set(mapa_cus))
    en_ambos, solo_ctl, solo_cus = [], [], []

    for m in todas:
        en_ctl = m in mapa_ctl
        en_cus = m in mapa_cus
        if en_ctl and en_cus:
            en_ambos.append({"matricula": m, "archivos_ctl": mapa_ctl[m], "archivos_cus": mapa_cus[m]})
        elif en_ctl:
            solo_ctl.append({"matricula": m, "archivos_ctl": mapa_ctl[m]})
        else:
            solo_cus.append({"matricula": m, "archivos_cus": mapa_cus[m]})

    return {"en_ambos": en_ambos, "solo_ctl": solo_ctl, "solo_cus": solo_cus}


# ---------------------------------------------------------------------------
# COMPARACIÓN — TITULAR DEL CTL vs. PROPIETARIO YA IDENTIFICADO EN LA APP
# ---------------------------------------------------------------------------

def comparar_titular_con_propietario_esperado(
    titulares_ctl: list,
    propietarios_plan: Optional[list] = None,
    propietario_inventario: Optional[str] = None,
    umbral: float = 0.6,
) -> dict:
    """
    Compara los titulares del CTL contra:
      - los propietarios detectados en el Informe/Plan AF (por número de
        identificación primero, por nombre como respaldo), y
      - el valor del campo PROPIETARIO del Inventario (por nombre).

    Retorna:
    {
      "coincide_plan": bool|None, "criterio_plan": str|None, "mejor_match_plan": dict|None,
      "coincide_inventario": bool|None, "similitud_inventario": float|None,
    }
    """
    propietarios_plan = propietarios_plan or []
    resultado = {
        "coincide_plan": None, "criterio_plan": None, "mejor_match_plan": None,
        "coincide_inventario": None, "similitud_inventario": None,
    }
    if not titulares_ctl:
        return resultado

    # --- vs. Informe/Plan AF: por número de identificación primero ---
    if propietarios_plan:
        match_numero = None
        for t in titulares_ctl:
            t_num = re.sub(r"\D", "", t.get("numero_id", ""))
            for p in propietarios_plan:
                p_num = re.sub(r"\D", "", p.get("numero_id", ""))
                if t_num and t_num == p_num:
                    match_numero = p
                    break
            if match_numero:
                break

        if match_numero:
            resultado["coincide_plan"] = True
            resultado["criterio_plan"] = "numero_id"
            resultado["mejor_match_plan"] = match_numero
        else:
            mejor_ratio, mejor_p = 0.0, None
            for t in titulares_ctl:
                for p in propietarios_plan:
                    ratio = _similitud(t.get("nombre", ""), p.get("nombre", ""))
                    if ratio > mejor_ratio:
                        mejor_ratio, mejor_p = ratio, p
            resultado["coincide_plan"] = mejor_ratio >= umbral
            resultado["criterio_plan"] = "nombre"
            resultado["mejor_match_plan"] = mejor_p

    # --- vs. Inventario: solo por nombre ---
    if propietario_inventario:
        mejor_ratio = 0.0
        for t in titulares_ctl:
            ratio = _similitud(t.get("nombre", ""), propietario_inventario)
            if ratio > mejor_ratio:
                mejor_ratio = ratio
        resultado["similitud_inventario"] = round(mejor_ratio, 2)
        resultado["coincide_inventario"] = mejor_ratio >= umbral

    return resultado
