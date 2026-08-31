# -*- coding: utf-8 -*-
"""
oficio_checklist.py — El Oficio de solicitud siempre incluye, al final, un
listado de los documentos que se anexan al trámite
("Formulario Único Nacional (FUN) diligenciado: Se adjunta el FUN ...",
"Certificados de Tradición y Libertad (CTL): Se adjunta el CTL ...", etc.).

Ese listado varía de un proyecto a otro (a veces trae más ítems, a veces
menos, y en cualquier orden), así que este módulo NO asume una lista fija:
la extrae del propio Oficio y luego la cruza contra:
  - los tipos de documento ya clasificados por la app (FUN, INFORME_AF,
    CTL, CUS, PODER, CEDULA, etc. — ver analyzer.clasificar_documento), y
  - los nombres de los archivos subidos (para ítems que la app no clasifica
    con un tipo propio, ej. RUT, Cámara de Comercio, Cartografía).

Así se puede avisar, antes de radicar, si el Oficio promete un documento
que en realidad no está en el paquete subido.
"""

import os
import re
import unicodedata
from collections import defaultdict

# Palabras clave de cada "tipo" que ya reconoce analyzer.py, para cruzar un
# ítem del checklist del Oficio (ej. "Certificados de Tradición y Libertad
# (CTL)") contra el tipo de documento ya clasificado (ej. "CTL") aunque la
# redacción no sea idéntica. Deliberadamente NO se incluyen palabras
# genéricas que aparecerían en varias categorías a la vez (ej. "forestal",
# "tecnico", "propietario"), porque eso causa que un ítem se cruce con el
# tipo equivocado solo por compartir una palabra común.
_TIPO_KEYWORDS = {
    "FUN": {"fun", "formulario", "unico", "nacional"},
    "INFORME_AF": {"informe", "plan", "aprovechamiento", "reposicion"},
    "INVENTARIO": {"inventario", "base", "datos"},
    "COMPENSACION": {"compensacion"},
    "APTITUD": {"aptitud", "estudio"},
    "COSTOS": {"costos", "presupuesto"},
    "OFICIO": {"oficio"},
    "CTL": {"certificado", "tradicion", "libertad", "ctl", "matricula", "inmobiliaria"},
    "CUS": {"certificacion", "alcaldia", "municipal", "planeacion"},
    "PODER": {"poder", "apoderado"},
    "CEDULA": {"cedula", "ciudadania", "identidad"},
}

_STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "para", "por", "con", "y", "al",
    "en", "su", "sus", "un", "una", "que", "se", "sobre", "emanado", "emanada",
}

# Ítems del checklist que Unergy considera que NO hace falta verificar en
# este cruce (ej. porque son documentos corporativos fijos que no cambian
# de proyecto a proyecto, o porque su ausencia no bloquea la radicación).
# Un ítem se descarta si TODAS estas palabras clave están presentes en él
# (no hace falta que sea la frase exacta — tolera variaciones de redacción).
_IGNORAR_PATRONES = [
    {"rut"},
    {"camara", "comercio"},
    {"cedula", "apoderado"},
    {"tecnico", "forestal"},  # "Documentos del técnico forestal"
]


def _item_ignorado(tokens: set) -> bool:
    return any(patron <= tokens for patron in _IGNORAR_PATRONES)


def _sin_tildes(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _tokens(texto: str) -> set:
    # Separa palabras pegadas en CamelCase (típico de nombres de archivo
    # como "InformeAF_COLSUCT283.docx" -> "Informe AF COLSUCT283") antes de
    # tokenizar, para que el cruce por nombre de archivo también funcione.
    texto = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", texto)
    texto = _sin_tildes(texto).lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return {t for t in texto.split() if len(t) > 2 and t not in _STOPWORDS}


def extraer_items_checklist_oficio(texto: str) -> list:
    """
    Devuelve la lista de nombres de documento que el Oficio dice anexar,
    ej. ["Formulario Único Nacional (FUN) diligenciado", "Certificados de
    Tradición y Libertad (CTL)", ...].

    Cada ítem del listado sigue el patrón "Título: Se adjunta/anexa/incluye
    ...", uno por línea/párrafo. No se asume una cantidad ni un orden fijo
    — se toma lo que el Oficio realmente liste.
    """
    items = []
    for linea in texto.split("\n"):
        linea = linea.strip(" \t-•")
        if not linea or ":" not in linea:
            continue
        titulo, resto = linea.split(":", 1)
        titulo = titulo.strip()
        resto = resto.strip()
        # Un ítem real del listado es un título corto (no una oración larga
        # que por casualidad tenga ":") seguido de una frase que confirma
        # que es una entrega ("se anexa/adjunta/incluye ..."), no otra cosa
        # con dos puntos en el oficio (ej. "Asunto: ...").
        if not (3 <= len(titulo) <= 90):
            continue
        if not re.search(r"\bse\s+(anexa|adjunta|incluye)n?\b", resto, re.IGNORECASE):
            continue
        items.append(titulo)
    return items


def _requerido(n_tokens: int) -> int:
    """Cuántas palabras clave deben coincidir para dar el match por
    válido. Ítems con pocas palabras (ej. 'Cédula del apoderado' -> solo
    'cedula'+'apoderado' tras quitar 'del') solo necesitan 1 coincidencia;
    ítems más largos necesitan 2, para no cruzar por una sola palabra común
    (ej. 'forestal') que aparece en varias categorías."""
    return 2 if n_tokens >= 3 else 1


def verificar_checklist_oficio(texto_oficio: str, documentos_tipo: dict) -> list:
    """
    documentos_tipo: {nombre_archivo: tipo} de TODOS los archivos subidos al
    paquete, en el ORDEN en que se subieron (incluye DESCONOCIDO — su nombre
    de archivo igual sirve para el cruce por nombre).

    Retorna una lista de dicts, uno por ítem del checklist del Oficio:
      {"item": <texto del ítem>, "encontrado": bool, "evidencia": <archivo o None>}

    Cuando el Oficio pide más de un documento del mismo tipo (ej. "Cédula
    del propietario" + "Cédula del apoderado"), cada uno se empareja con un
    archivo DISTINTO de ese tipo, en el orden en que se subieron — si solo
    se subió uno, el segundo ítem queda marcado como faltante.
    """
    items = extraer_items_checklist_oficio(texto_oficio)

    # Cola de archivos disponibles por tipo, respetando el orden de subida.
    cola_por_tipo = defaultdict(list)
    for nombre, tipo in documentos_tipo.items():
        cola_por_tipo[tipo].append(nombre)

    usados = set()
    resultado = []

    for item in items:
        tokens = _tokens(item)
        if _item_ignorado(tokens):
            continue
        requerido = _requerido(len(tokens))

        # 1) ¿Coincide con algún "tipo" ya clasificado por la app?
        mejor_tipo, mejor_overlap = None, 0
        for tipo, kw in _TIPO_KEYWORDS.items():
            overlap = len(tokens & kw)
            if overlap > mejor_overlap:
                mejor_overlap, mejor_tipo = overlap, tipo
        if mejor_overlap >= requerido and cola_por_tipo.get(mejor_tipo):
            nombre = cola_por_tipo[mejor_tipo].pop(0)
            usados.add(nombre)
            resultado.append({"item": item, "encontrado": True, "evidencia": f"{nombre} ({mejor_tipo})"})
            continue

        # 2) Si no hay tipo (o ya no quedan archivos de ese tipo), buscar por
        # nombre de archivo entre los que aún no se han usado como evidencia.
        mejor_nombre, mejor_overlap_n = None, 0
        for nombre in documentos_tipo:
            if nombre in usados:
                continue
            overlap = len(tokens & _tokens(os.path.splitext(nombre)[0]))
            if overlap > mejor_overlap_n:
                mejor_overlap_n, mejor_nombre = overlap, nombre
        if mejor_overlap_n >= 1:
            usados.add(mejor_nombre)
            resultado.append({"item": item, "encontrado": True, "evidencia": mejor_nombre})
        else:
            resultado.append({"item": item, "encontrado": False, "evidencia": None})

    return resultado
