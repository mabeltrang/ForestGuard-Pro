# -*- coding: utf-8 -*-
"""
poder_forestal_checker.py — El Poder Forestal es el documento donde el
propietario del predio autoriza/apodera a Unergy (u otro solicitante) para
adelantar el trámite de aprovechamiento forestal ante la Corporación. En su
texto normalmente aparecen los tres datos que se quieren cruzar:

  - Nombre del propietario/poderdante
  - Su número de identificación (C.C./NIT/C.E.)
  - El número de matrícula inmobiliaria del predio sobre el que autoriza

Este módulo extrae esos tres datos del texto del Poder Forestal y los
compara contra:
  - el titular de derechos reales de dominio del CTL (nombre + C.C.) y su
    matrícula (ctl_cus_checker.py),
  - los propietarios detectados en el Informe/Plan de Aprovechamiento
    (propietario_checker.py),
  - el campo PROPIETARIO del Inventario (propietario_checker.py),
  - los datos leídos de la foto/PDF de la cédula (cedula_checker.py), si se
    subió.

Reutiliza los mismos extractores de nombre+identificación y de matrícula que
ya existen en ctl_cus_checker.py (misma lógica, un solo lugar de verdad para
esos patrones), y agrega solo la función de cruce específica del Poder.
"""

import re
from typing import Optional

from ctl_cus_checker import (
    extraer_matriculas,
    _normalizar_texto,
    _similitud,
    _normalizar_matricula,
)

# Mismo patrón de prosa "identificado con C.C./NIT/C.E." usado en
# propietario_checker.py y ctl_cus_checker.py — el Poder Forestal casi
# siempre trae al propietario/poderdante mencionado así.
_PATRON_PROPIETARIO_PODER = re.compile(
    r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9&.\- ]{3,80}?)"
    r"\s*,?\s*identificad[oa]?\s+con\s+"
    r"(C\.?\s?C\.?|NIT|C\.?E\.?|Ced(?:ula)?)\.?\s*([\d.,\-]+)",
    re.IGNORECASE,
)

_PREFIJOS_TRATAMIENTO = re.compile(
    r"^(la\s+se[ñn]ora|el\s+se[ñn]or(?:\(a\))?|la\s+sociedad|el\s+se[ñn]or\s*a)\s+",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# EXTRACCIÓN
# ---------------------------------------------------------------------------

def extraer_propietario_poder(texto: str) -> list:
    """
    Retorna [{"nombre","tipo_id","numero_id"}, ...] mencionados en el Poder.
    Se normaliza el texto a espacios simples antes de buscar, porque un
    nombre partido en dos líneas por ajuste de línea (típico del texto
    extraído de PDF/DOCX) haría fallar el patrón si se buscara tal cual.
    """
    texto_plano = re.sub(r"\s+", " ", texto)
    hallazgos = []
    vistos = set()
    for m in _PATRON_PROPIETARIO_PODER.finditer(texto_plano):
        nombre_raw, tipo_id, numero_id = m.groups()
        nombre = _PREFIJOS_TRATAMIENTO.sub("", nombre_raw).strip(" ,.")
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


def extraer_datos_poder_forestal(texto: str) -> dict:
    """{"propietarios": [...], "matriculas": [...]} extraídos del Poder Forestal."""
    return {
        "propietarios": extraer_propietario_poder(texto),
        "matriculas": extraer_matriculas(texto),
    }


# ---------------------------------------------------------------------------
# CRUCE
# ---------------------------------------------------------------------------

def _mejor_match_por_numero_o_nombre(propietarios_poder: list, otra_lista: list, umbral: float):
    """
    Busca primero coincidencia exacta por número de identificación (normalizado
    a solo dígitos) y, si no hay, la mejor coincidencia por similitud de nombre.
    Retorna (coincide: bool|None, criterio: str|None, mejor_match: dict|None).
    """
    if not propietarios_poder or not otra_lista:
        return None, None, None

    for p in propietarios_poder:
        p_num = re.sub(r"\D", "", p.get("numero_id", ""))
        if not p_num:
            continue
        for o in otra_lista:
            o_num = re.sub(r"\D", "", o.get("numero_id", ""))
            if o_num and o_num == p_num:
                return True, "numero_id", o

    mejor_ratio, mejor_o = 0.0, None
    for p in propietarios_poder:
        for o in otra_lista:
            ratio = _similitud(p.get("nombre", ""), o.get("nombre", ""))
            if ratio > mejor_ratio:
                mejor_ratio, mejor_o = ratio, o

    return (mejor_ratio >= umbral), "nombre", mejor_o


def comparar_poder_forestal(
    datos_poder: dict,
    titulares_ctl: Optional[list] = None,
    matriculas_ctl: Optional[list] = None,
    propietarios_plan: Optional[list] = None,
    propietario_inventario: Optional[str] = None,
    datos_cedula: Optional[dict] = None,
    umbral: float = 0.6,
) -> dict:
    """
    datos_poder: salida de extraer_datos_poder_forestal().
    titulares_ctl: lista combinada de todos los titulares extraídos de los CTL subidos.
    matriculas_ctl: lista combinada de todas las matrículas extraídas de los CTL subidos.
    propietarios_plan: salida de propietario_checker.extraer_propietarios_docx().
    propietario_inventario: valor crudo del campo PROPIETARIO del Inventario (xlsx).
    datos_cedula: salida de cedula_checker.extraer_datos_cedula() (nombre/numero_identificacion), si se subió.

    Retorna un dict con, para cada fuente, {"coincide", "criterio", "mejor_match"}
    (o para matrícula/inventario/cédula la variante correspondiente).
    """
    propietarios_poder = datos_poder.get("propietarios", [])
    matriculas_poder = datos_poder.get("matriculas", [])

    resultado = {
        "propietarios_poder": propietarios_poder,
        "matriculas_poder": matriculas_poder,
        "coincide_ctl_nombre": None, "criterio_ctl": None, "mejor_match_ctl": None,
        "coincide_matricula_ctl": None, "matricula_ctl_match": None,
        "coincide_plan": None, "criterio_plan": None, "mejor_match_plan": None,
        "coincide_inventario": None, "similitud_inventario": None,
        "coincide_cedula": None, "similitud_cedula": None,
    }

    # --- vs. CTL (titular por nombre/número) ---
    if titulares_ctl:
        coincide, criterio, match = _mejor_match_por_numero_o_nombre(
            propietarios_poder, titulares_ctl, umbral
        )
        resultado["coincide_ctl_nombre"] = coincide
        resultado["criterio_ctl"] = criterio
        resultado["mejor_match_ctl"] = match

    # --- vs. CTL (matrícula) ---
    if matriculas_ctl and matriculas_poder:
        set_ctl = {_normalizar_matricula(m) for m in matriculas_ctl}
        matches = [m for m in matriculas_poder if _normalizar_matricula(m) in set_ctl]
        resultado["coincide_matricula_ctl"] = bool(matches)
        resultado["matricula_ctl_match"] = matches or None

    # --- vs. Informe/Plan AF ---
    if propietarios_plan:
        coincide, criterio, match = _mejor_match_por_numero_o_nombre(
            propietarios_poder, propietarios_plan, umbral
        )
        resultado["coincide_plan"] = coincide
        resultado["criterio_plan"] = criterio
        resultado["mejor_match_plan"] = match

    # --- vs. Inventario (solo nombre) ---
    if propietario_inventario and propietarios_poder:
        mejor_ratio = 0.0
        for p in propietarios_poder:
            ratio = _similitud(p.get("nombre", ""), propietario_inventario)
            if ratio > mejor_ratio:
                mejor_ratio = ratio
        resultado["similitud_inventario"] = round(mejor_ratio, 2)
        resultado["coincide_inventario"] = mejor_ratio >= umbral

    # --- vs. Cédula leída por visión ---
    if datos_cedula and propietarios_poder:
        cc_cedula = re.sub(r"\D", "", datos_cedula.get("numero_identificacion") or "")
        nombre_cedula = datos_cedula.get("nombre") or ""
        if cc_cedula:
            match_num = next(
                (p for p in propietarios_poder if re.sub(r"\D", "", p.get("numero_id", "")) == cc_cedula),
                None,
            )
            if match_num:
                resultado["coincide_cedula"] = True
                resultado["similitud_cedula"] = 1.0
            else:
                mejor_ratio = max(
                    (_similitud(nombre_cedula, p.get("nombre", "")) for p in propietarios_poder),
                    default=0.0,
                )
                resultado["similitud_cedula"] = round(mejor_ratio, 2)
                resultado["coincide_cedula"] = mejor_ratio >= umbral
        elif nombre_cedula:
            mejor_ratio = max(
                (_similitud(nombre_cedula, p.get("nombre", "")) for p in propietarios_poder),
                default=0.0,
            )
            resultado["similitud_cedula"] = round(mejor_ratio, 2)
            resultado["coincide_cedula"] = mejor_ratio >= umbral

    return resultado
