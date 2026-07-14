"""
analyzer.py — Validador de paquetes forestales sin API de IA.

Patrones basados en docs reales Unergy:
- Separador de miles variable: coma ($ 526,468) o punto ($ 332.122)
- Costo aprovechamiento: párrafo "valor aproximado de ... ($ XXX COP)" + tabla con Total
- Costo compensación: fila "Valor total compensación (3 años)" + Total al final
- Costo instalación: "TOTAL VALOR DEL PROYECTO EN NÚMEROS = (A+B)"
"""

import re


# ---------------------------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------------------------

def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.lower().strip())


def _normalizar_num_str(val: str) -> str:
    """
    Normaliza un string numérico según la convención del usuario:
    '.' = separador decimal, ',' = separador de miles.

    - La coma SIEMPRE se elimina (separador de miles).
    - Si queda más de un punto, son separadores de miles de otro sistema
      (ej. '332.122.500') y se eliminan todos.
    - Si queda un solo punto, es el separador decimal y se conserva
      (ej. '2.771' m3 sigue siendo 2.771, no 2771).
    """
    val = val.strip()
    val = val.replace(",", "")
    if val.count(".") > 1:
        val = val.replace(".", "")
    return val


def _cop_a_entero(val: str) -> str | None:
    """Normaliza un valor monetario COP a entero sin separadores ni centavos."""
    if not val:
        return None
    val = val.replace("$", "").strip()
    val = _normalizar_num_str(val)
    if "." in val:
        # Único punto restante = separador decimal (centavos) -> se descartan,
        # el peso colombiano se maneja como entero.
        val = val.split(".")[0]
    val = val.strip()
    return val if val.isdigit() else None


def _extraer_cop_parrafo(texto: str, patron_inicio: str) -> str | None:
    """
    Extrae el valor COP del párrafo introductorio de una sección de costos.
    Patrón: "valor aproximado de PALABRAS EN MAYÚSCULAS ($ 526,468 COP)"
    """
    m = re.search(patron_inicio, texto, re.IGNORECASE)
    if not m:
        return None
    segmento = texto[m.start(): m.start() + 1000]
    # Buscar ($ X,XXX,XXX COP) o ($ X.XXX.XXX COP)
    m2 = re.search(r'\(\s*\$\s*([\d][,\.\d]+)\s*COP\)', segmento, re.IGNORECASE)
    if m2:
        return _cop_a_entero(m2.group(1))
    # Alternativa: "$ 526,468" sin paréntesis cerca de "valor"
    m3 = re.search(r'valor\s+aproximado[^\$]{0,60}\$\s*([\d][,\.\d]+)', segmento, re.IGNORECASE)
    if m3:
        return _cop_a_entero(m3.group(1))
    return None


def _extraer_cop_tabla_total(texto: str, patron_inicio: str) -> str | None:
    """
    Extrae el valor de la fila 'Total' al final de una tabla de costos.
    Busca la última fila Total dentro de la sección.
    """
    m = re.search(patron_inicio, texto, re.IGNORECASE)
    if not m:
        return None
    segmento = texto[m.start(): m.start() + 5000]

    # Buscar todas las filas | Total | ... | $ X,XXX,XXX |
    # Dos formatos: coma miles ($526,468) o punto miles ($332.122)
    candidatos = re.findall(
        r'\|\s*\*?\*?Total\*?\*?\s*\|[^\|]*\|\s*\*?\*?\s*\$?\s*([\d][\d,\.]+)\s*\*?\*?\s*\|',
        segmento, re.IGNORECASE
    )
    # También buscar formato "Total | $ X,XXX,XXX" sin columnas adicionales
    candidatos2 = re.findall(
        r'\|\s*\*?\*?Total\*?\*?\s*\|\s*\*?\*?\$?\s*([\d][\d,\.]+)\s*\*?\*?\s*\|',
        segmento, re.IGNORECASE
    )
    todos = candidatos + candidatos2

    if todos:
        # El último total del segmento es el grand total
        val = todos[-1]
        return _cop_a_entero(val)
    return None


def _extraer_numero(patron: str, texto: str, flags=re.IGNORECASE) -> str | None:
    m = re.search(patron, texto, flags)
    if not m:
        return None
    val = _normalizar_num_str(m.group(1).strip())
    return val if val else None


def _extraer_costo_compensacion_total(texto: str) -> str | None:
    """
    Extrae el costo TOTAL de compensación, evitando confundirlo con el valor
    unitario por hectárea (ej: $16.000.000/ha o $16,000,000 por hectárea).

    Busca en orden:
    0. Patrón explícito "TOTAL INVERSIÓN DEL PLAN" (el más confiable, usado en
       las plantillas de Costos y Presupuesto).
    1. Patrones explícitos de TOTAL que no estén seguidos de '/ha' o 'por hectárea'
    2. Última fila Total de la tabla de compensación
    3. Formato 'COP $XX,XXX,XXX' que NO esté asociado a '/ha'
    """
    # Patrón 0: "TOTAL INVERSIÓN DEL PLAN $ 41,366,592.00" — el total real y
    # explícito del presupuesto, siempre debe preferirse sobre cualquier valor
    # unitario o por hectárea que aparezca antes en el texto.
    m0 = re.search(
        r"TOTAL\s+INVERSI[OÓ]N\s+DEL\s+PLAN[^\d]{0,20}\$?\s*([\d][,\.\d]+)",
        texto, re.IGNORECASE
    )
    if m0:
        val = _cop_a_entero(m0.group(1))
        if val and int(val) > 1_000_000:
            return val

    # Patrón 1: "Valor total compensación (3 años): $XX,XXX,XXX" o similar
    for pat in [
        r"valor\s+total\s+(?:de\s+la\s+)?compensaci[oó]n[^$\d]{0,80}\$\s*([\d][,\.\d]+)",
        r"costo\s+total\s+(?:de\s+la\s+)?compensaci[oó]n[^$\d]{0,80}\$\s*([\d][,\.\d]+)",
        r"total\s+compensaci[oó]n[^$\d]{0,60}\$\s*([\d][,\.\d]+)",
        r"presupuesto\s+total[^$\d]{0,60}\$\s*([\d][,\.\d]+)",
    ]:
        m = re.search(pat, texto, re.IGNORECASE)
        if m:
            # Verificar que el valor NO esté seguido de "/ha" o "por hectárea".
            # Se normalizan los espacios en blanco (incluyendo saltos de línea)
            # antes de comparar, porque el texto extraído de PDF frecuentemente
            # parte "por hectárea" en dos líneas ("por \nhectárea"), lo que
            # antes hacía que el filtro de exclusión no detectara el valor
            # unitario y lo confundiera con el total.
            pos_fin = m.end()
            siguiente = _normalizar(texto[pos_fin: pos_fin + 40])
            if "/ha" not in siguiente and "por hect" not in siguiente and "hectárea" not in siguiente:
                val = _cop_a_entero(m.group(1))
                if val and int(val) > 1_000_000:  # filtrar valores unitarios menores
                    return val

    # Patrón 2: fila Total en tabla de compensación (última ocurrencia)
    val = _extraer_cop_tabla_total(
        texto,
        r"[Vv]alor\s+total\s+compensaci[oó]n|[Tt]abla\s+\d+.*[Cc]ostos?\s+de\s+(?:reposici[oó]n|compensaci[oó]n)"
    )
    if val and int(val) > 1_000_000:
        return val

    # Patrón 3: "COP $XX,XXX,XXX" que no sea unitario
    for m in re.finditer(r'COP\s*\$\s*([\d][,\.\d]+)', texto, re.IGNORECASE):
        siguiente = _normalizar(texto[m.end(): m.end() + 40])
        if "/ha" not in siguiente and "por hect" not in siguiente:
            val = _cop_a_entero(m.group(1))
            if val and int(val) > 1_000_000:
                return val

    # Fallback: párrafo con "plan de reposición/compensación forestal corresponde"
    return _extraer_cop_parrafo(
        texto,
        r"plan\s+de\s+(?:reposici[oó]n|compensaci[oó]n)\s+forestal\s+corresponde"
    )


def _extraer_texto(patron: str, texto: str, flags=re.IGNORECASE) -> str | None:
    m = re.search(patron, texto, flags)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# EXTRACCIÓN POR TIPO DE DOCUMENTO
# ---------------------------------------------------------------------------

def extraer_fun(texto: str) -> dict:
    r = {}

    r["individuos"] = _extraer_numero(
        r"cantidad\s+total[^\d]{0,30}(\d{1,4})", texto
    )
    r["volumen_m3"] = _extraer_numero(
        r"cantidad\s+total[^\d]{0,80}([\d,\.]+)\s*m(?:etros?\s*c[uú]bicos?|3|³)", texto
    ) or _extraer_numero(
        r"([\d,\.]+)\s*m(?:etros?\s*c[uú]bicos?|3|³)\s*de\s*volumen", texto
    )
    r["area_ha"] = _extraer_numero(
        r"superficie\s*\(ha\)[^\d]{0,20}([\d,\.]+)", texto
    ) or _extraer_numero(
        r"[áa]rea[^\d]{0,30}([\d,\.]+)\s*ha", texto
    )
    # Costo instalación: campo "Costo del Proyecto, Obra o Actividad"
    r["costo_instalacion"] = _extraer_numero(
        r"costo\s+del\s+proyecto[,\s]+obra[^\d]{0,40}([\d\.,]{6,})", texto
    ) or _extraer_numero(
        r"costo\s+del\s+proyecto[^\d]{0,40}([\d\.,]{6,})", texto
    )
    r["municipio"] = _extraer_texto(
        r"municipio[:\s]+([A-Za-záéíóúÁÉÍÓÚñÑ\s]+?)(?:\n|,|departamento)", texto
    )
    r["nombre_proyecto"] = _extraer_texto(
        r"nombre\s+del\s+proyecto[:\s]+([^\n]{5,80})", texto
    ) or _extraer_texto(
        r"minigranja\s+solar\s+([A-Za-záéíóúÁÉÍÓÚñÑ\s\w_]+?)(?:\n|\.)", texto
    )
    return r


def extraer_informe_af(texto: str) -> dict:
    """
    Informe AF — contiene costo aprovechamiento, y a veces también costo reposición.
    """
    r = {}

    # Individuos
    r["individuos_intro"] = _extraer_numero(
        r"aprovechamiento\s+(?:forestal\s+)?de\s+(\d{1,4})\s+[áa]rboles?", texto
    )
    # Fila Total en tabla de especies: | Total | 8 |
    m_total = re.search(r'\|\s*\*?\*?Total\*?\*?\s*\|\s*\*?\*?(\d{1,4})\*?\*?\s*\|', texto)
    r["individuos_tabla"] = m_total.group(1) if m_total else None
    r["individuos"] = r["individuos_intro"] or r["individuos_tabla"]

    # Individuos a reponer — "siembra de X individuos" o "15 nuevos individuos"
    r["individuos_reponer"] = _extraer_numero(
        r"siembra\s+de\s+(\d{1,4})\s*(?:individuos?|[áa]rboles?|pl[áa]ntulas?)", texto
    ) or _extraer_numero(
        r"plantaci[oó]n\s+de\s+(?:un\s+total\s+de\s+)?(\d{1,4})\s*(?:nuevos?\s+)?(?:individuos?|[áa]rboles?)", texto
    ) or _extraer_numero(
        r"total\s+de\s+(\d{1,4})\s*(?:nuevos?\s+)?(?:individuos?|[áa]rboles?)", texto
    )

    # Factor de reposición
    r["factor_reposicion"] = _extraer_numero(
        r"siembra\s+de\s+(?:cinco|cuatro|tres|dos|diez|\d{1,2})\s*\((\d{1,2})\)\s*nuevos?\s+[áa]rboles?\s+por\s+cada", texto
    ) or _extraer_numero(
        r"factor\s+de\s+reposici[oó]n[^\d]{0,20}(\d{1,2})", texto
    ) or _extraer_numero(
        r"(\d{1,2})\s*[áa]rboles?\s+por\s+(?:cada\s+)?(?:individuo|[áa]rbol)\s+talado", texto
    )

    # Volumen total — del párrafo resumen (no tabla de especies)
    r["volumen_m3"] = _extraer_numero(
        r"con\s+([\d,\.]+)\s*metros?\s*c[uú]bicos?\s*\(m[³3]\)", texto
    ) or _extraer_numero(
        r"asciende\s+a[^\d]{0,30}([\d,\.]+)\s*metros?\s*c[uú]bicos?", texto
    ) or _extraer_numero(
        r"([\d,\.]+)\s*metros?\s*c[uú]bicos?\s*\(m[³3]\)\s*de\s*madera", texto
    )

    r["area_ha"] = _extraer_numero(
        r"un\s+[áa]rea\s+de\s+([\d,\.]+)\s*(?:hect[áa]reas?|ha)", texto
    ) or _extraer_numero(
        r"[áa]rea\s+de\s+([\d,\.]+)\s*(?:hect[áa]reas?|ha)\b", texto
    )

    potencias = re.findall(r"([\d,\.]+)\s*k[Ww][Pp]?\b", texto, re.IGNORECASE)
    r["potencia_kwp"] = _normalizar_num_str(potencias[0]) if potencias else None

    for nombre in ["afinia", "cens", "aire", "air-e", "enel", "celsia", "codensa", "epsa", "chec", "essa"]:
        if nombre in texto.lower():
            r["distribuidora"] = nombre.upper()
            break
    else:
        r["distribuidora"] = None

    # Costo aprovechamiento — del párrafo "($ 526,468 COP)" antes de la tabla
    r["costo_aprovechamiento"] = _extraer_cop_parrafo(
        texto, r"costo\s+estimado\s+para\s+la\s+tala\s+y\s+aprovechamiento"
    )
    # Fallback: última fila Total de la tabla de costos de aprovechamiento
    if not r["costo_aprovechamiento"]:
        r["costo_aprovechamiento"] = _extraer_cop_tabla_total(
            texto, r"[Tt]abla\s+\d+\.?\s*[Cc]ostos?\s+de\s+aprovechamiento"
        )

    # Costo compensación/reposición (si está en este doc — mismo patrón de párrafo)
    r["costo_compensacion"] = _extraer_cop_parrafo(
        texto, r"plan\s+de\s+(?:reposici[oó]n|compensaci[oó]n)\s+forestal\s+corresponde|costos\s+totales\s+de\s+las\s+actividades\s+de\s+(?:compensaci[oó]n|reposici[oó]n)"
    )
    if not r["costo_compensacion"]:
        r["costo_compensacion"] = _extraer_cop_tabla_total(
            texto, r"[Tt]abla\s+\d+\.?\s*[Cc]ostos?\s+de\s+reposici[oó]n|[Vv]alor\s+total\s+compensaci[oó]n"
        )

    r["nombre_proyecto"] = _extraer_texto(
        r"(?:informe|plan|documento\s+técnico)\s+para\s+el\s+aprovechamiento[^\n]{0,5}\n([^\n]{5,80})", texto
    )

    return r


def extraer_compensacion(texto: str) -> dict:
    """Plan de Compensación como documento separado."""
    r = {}

    r["individuos_reponer"] = _extraer_numero(
        r"siembra\s+de\s+(\d{1,4})\s*(?:individuos?|[áa]rboles?|pl[áa]ntulas?)", texto
    ) or _extraer_numero(
        r"plantaci[oó]n\s+de\s+(?:un\s+total\s+de\s+)?(\d{1,4})\s*(?:nuevos?\s+)?(?:individuos?|[áa]rboles?)", texto
    )

    r["factor_reposicion"] = _extraer_numero(
        r"siembra\s+de\s+(?:cinco|cuatro|tres|dos|diez|\d{1,2})\s*\((\d{1,2})\)\s*nuevos?\s+[áa]rboles?\s+por\s+cada", texto
    ) or _extraer_numero(
        r"factor\s+de\s+reposici[oó]n[^\d]{0,20}(\d{1,2})", texto
    )

    # Costo — "COP $34,320,000" o tabla Total
    # Costo compensación — usa extractor robusto que ignora valores unitarios /ha
    r["costo_compensacion"] = _extraer_costo_compensacion_total(texto)

    r["nombre_proyecto"] = _extraer_texto(
        r"(?:plan|programa)\s+de\s+compensaci[oó]n\s+([^\n]{5,80})", texto
    )

    return r


def extraer_aptitud_suelo(texto: str) -> dict:
    r = {}

    r["individuos"] = _extraer_numero(
        r"(\d{1,4})\s*(?:individuos?|[áa]rboles?)\s*(?:a\s+)?(?:aprovechar|talar|intervenir)", texto
    )
    r["area_ha"] = _extraer_numero(
        r"[áa]rea[^\d]{0,30}([\d,\.]+)\s*(?:hect[áa]reas?|ha\b)", texto
    )
    potencias = re.findall(r"([\d,\.]+)\s*k[Ww][Pp]?\b", texto, re.IGNORECASE)
    r["potencia_kwp"] = _normalizar_num_str(potencias[0]) if potencias else None

    for nombre in ["afinia", "cens", "aire", "air-e", "enel", "celsia", "codensa", "epsa", "chec", "essa"]:
        if nombre in texto.lower():
            r["distribuidora"] = nombre.upper()
            break
    else:
        r["distribuidora"] = None

    m = re.search(r"conclusi[oó]n(?:es)?[\s\S]{0,50}\n([\s\S]{50,400}?)(?:\n\n|\Z)", texto, re.IGNORECASE)
    r["conclusion"] = m.group(1).strip()[:300] if m else None

    r["nombre_proyecto"] = _extraer_texto(
        r"informe\s+(?:de\s+)?aptitud\s+([^\n]{5,80})", texto
    )
    return r


def extraer_costos(texto: str) -> dict:
    """
    Doc Costos y Presupuesto — tres secciones:
    1. COSTOS DEL APROVECHAMIENTO FORESTAL → Total $ 526,468
    2. COSTOS DE LA COMPENSACIÓN → Total $ 15,739,846
    3. COSTOS DE LA IMPLEMENTACIÓN → TOTAL VALOR DEL PROYECTO = $ 495,705,000
    """
    r = {}

    r["individuos"] = _extraer_numero(
        r"aprovechamiento\s+(?:forestal\s+)?de\s+(\d{1,4})\s+[áa]rboles?", texto
    )
    r["individuos_reponer"] = _extraer_numero(
        r"siembra\s+de\s+(\d{1,4})\s*(?:individuos?|[áa]rboles?)", texto
    )
    # Volumen — "Producto: Tala | Unidad: m3 | Cantidad: 2.771" o "| Tala | m3 | 2.771 |"
    r["volumen_m3"] = _extraer_numero(
        r'[Pp]roducto:\s*Tala\s*\|\s*[Uu]nidad:\s*m3\s*\|\s*[Cc]antidad:\s*([\d,\.]+)', texto
    ) or _extraer_numero(
        r'\|\s*Tala\s*\|\s*m3\s*\|\s*([\d,\.]+)', texto
    )

    # Costo aprovechamiento — párrafo + tabla
    r["costo_aprovechamiento"] = _extraer_cop_parrafo(
        texto, r"costos?\s+del?\s+aprovechamiento\s+forestal"
    )
    if not r["costo_aprovechamiento"]:
        r["costo_aprovechamiento"] = _extraer_cop_tabla_total(
            texto, r"[Tt]abla\s+1[\.\s]*[Cc]ostos?\s+de\s+aprovechamiento"
        )

    # Costo compensación — mismo patrón de párrafo que aprovechamiento
    # Costo compensación — usa extractor robusto que ignora valores unitarios /ha
    r["costo_compensacion"] = _extraer_costo_compensacion_total(texto)

    # Costo instalación — "TOTAL VALOR DEL PROYECTO EN NÚMEROS = (A+B) | 495,705,000"
    r["costo_instalacion"] = _extraer_numero(
        r"TOTAL\s+VALOR\s+DEL\s+PROYECTO\s+EN\s+N[ÚU]MEROS[^\d]{0,30}([\d\.,]{6,})", texto
    ) or _extraer_numero(
        r"Total\s+de\s+la\s+inversi[oó]n\s+y\s+la\s+operaci[oó]n[^\d]{0,10}\$\s*([\d\.,]{6,})", texto
    )

    return r


def extraer_oficio(texto: str) -> dict:
    r = {}

    r["individuos"] = _extraer_numero(
        r"aprovechamiento\s+forestal\s+de\s+(\d{1,4})\s+[áa]rboles?", texto
    )
    r["nombre_proyecto"] = _extraer_texto(
        r"proyecto\s+[\"«]?([^\n\"»]{5,80})[\"»]?", texto
    )
    for nombre in ["afinia", "cens", "aire", "air-e", "enel", "celsia", "codensa", "epsa", "chec", "essa"]:
        if nombre in texto.lower():
            r["distribuidora"] = nombre.upper()
            break
    else:
        r["distribuidora"] = None

    potencias = re.findall(r"([\d,\.]+)\s*k[Ww][Pp]?\b", texto, re.IGNORECASE)
    r["potencia_kwp"] = _normalizar_num_str(potencias[0]) if potencias else None

    return r


# ---------------------------------------------------------------------------
# CLASIFICACIÓN
# ---------------------------------------------------------------------------

TIPOS = {
    "FUN": [
        "formulario único nacional", "fun", "formato único",
        "superficie (ha)", "costo del proyecto, obra"
    ],
    "INFORME_AF": [
        "informe de aprovechamiento", "plan de aprovechamiento",
        "documento técnico para el aprovechamiento",
        "factor de reposición", "árboles aislados", "costos de aprovechamiento"
    ],
    "COMPENSACION": [
        "plan de compensación", "plan de reposición", "programa de compensación",
        "compensacion forestal", "reposicion forestal", "restauración ecológica"
    ],
    "APTITUD": [
        "aptitud del suelo", "aptitud de suelo", "vocación del suelo",
        "estudio técnico", "uso del suelo"
    ],
    "COSTOS": [
        "costos y presupuesto", "costos del aprovechamiento, de la compensación",
        "total valor del proyecto", "costos de la implementación",
        "costos de la compensación", "costos de inversión"
    ],
    "OFICIO": [
        "solicitud de aprovechamiento forestal",
        "cordial saludo", "se permite presentar",
        "adjunta la siguiente documentación", "oficio"
    ],
}


def clasificar_documento(nombre_archivo: str, texto: str) -> str:
    nombre = nombre_archivo.lower()
    texto_n = _normalizar(texto[:4000])

    puntajes = {tipo: 0 for tipo in TIPOS}

    for tipo, palabras_clave in TIPOS.items():
        for p in palabras_clave:
            if p in nombre:
                puntajes[tipo] += 3
            if p in texto_n:
                puntajes[tipo] += 1

    mejor = max(puntajes, key=puntajes.get)
    return mejor if puntajes[mejor] > 0 else "DESCONOCIDO"


# ---------------------------------------------------------------------------
# COMPARACIÓN Y ANÁLISIS
# ---------------------------------------------------------------------------

def _comparar(val_a, val_b, tolerancia_pct: float = 1.0) -> bool:
    if val_a is None or val_b is None:
        return True
    try:
        a = float(val_a)
        b = float(val_b)
        if a == 0 and b == 0:
            return True
        diff_pct = abs(a - b) / max(abs(a), abs(b)) * 100
        return diff_pct <= tolerancia_pct
    except ValueError:
        return str(val_a).strip().lower() == str(val_b).strip().lower()


def _fmt(val) -> str:
    """Formatea un valor numérico como COP legible o lo devuelve tal cual."""
    if val is None:
        return "—"
    try:
        n = int(float(val))
        if n > 10000:
            return f"${n:,}".replace(",", ".")
        return str(val)
    except Exception:
        return str(val) if val else "—"


def analizar_paquete(documentos: dict) -> dict:
    fun  = documentos.get("FUN", {})
    af   = documentos.get("INFORME_AF", {})
    comp = documentos.get("COMPENSACION", {})
    apt  = documentos.get("APTITUD", {})
    cos  = documentos.get("COSTOS", {})
    ofi  = documentos.get("OFICIO", {})

    # Costo compensación: priorizar doc separado, fallback al AF
    costo_comp_val   = comp.get("costo_compensacion") or af.get("costo_compensacion")
    costo_comp_label = "Plan Comp." if comp.get("costo_compensacion") else "Informe AF"

    filas_cotejo = []
    incoherencias = []

    def fila(dato, vals: dict):
        valores_presentes = {k: v for k, v in vals.items() if v is not None}
        valores_lista = list(valores_presentes.values())

        if len(valores_lista) < 2:
            consistente = "—"
        else:
            consistente = "✅"
            ref = valores_lista[0]
            for v in valores_lista[1:]:
                if not _comparar(ref, v):
                    consistente = "❌"
                    break

        filas_cotejo.append({
            "dato": dato,
            "FUN": _fmt(vals.get("FUN")),
            "Informe AF": _fmt(vals.get("Informe AF")),
            "Plan Comp.": _fmt(vals.get("Plan Comp.")),
            "Aptitud": _fmt(vals.get("Aptitud")),
            "Costos": _fmt(vals.get("Costos")),
            "Oficio": _fmt(vals.get("Oficio")),
            "✓": consistente,
        })

        if consistente == "❌":
            incoherencias.append({
                "dato": dato,
                "valores": {k: _fmt(v) for k, v in vals.items() if v is not None}
            })

    # ---- Filas ----
    fila("Individuos a aprovechar", {
        "FUN": fun.get("individuos"),
        "Informe AF": af.get("individuos"),
        "Aptitud": apt.get("individuos"),
        "Costos": cos.get("individuos"),
        "Oficio": ofi.get("individuos"),
    })
    fila("Volumen aprovechamiento (m³)", {
        "Informe AF": af.get("volumen_m3"),
        "Costos": cos.get("volumen_m3"),
    })
    fila("Individuos a reponer", {
        "Informe AF": af.get("individuos_reponer"),
        "Plan Comp.": comp.get("individuos_reponer"),
        "Costos": cos.get("individuos_reponer"),
    })
    fila("Área del predio (ha)", {
        "FUN": fun.get("area_ha"),
        "Informe AF": af.get("area_ha"),
        "Aptitud": apt.get("area_ha"),
    })
    fila("Potencia del proyecto (kWp)", {
        "Informe AF": af.get("potencia_kwp"),
        "Aptitud": apt.get("potencia_kwp"),
        "Oficio": ofi.get("potencia_kwp"),
    })
    fila("Empresa distribuidora", {
        "Informe AF": af.get("distribuidora"),
        "Aptitud": apt.get("distribuidora"),
        "Oficio": ofi.get("distribuidora"),
    })
    fila("💰 Costo aprovechamiento (COP)", {
        "Informe AF": af.get("costo_aprovechamiento"),
        "Costos": cos.get("costo_aprovechamiento"),
    })
    fila("💰 Costo compensación (COP)", {
        costo_comp_label: costo_comp_val,
        "Costos": cos.get("costo_compensacion"),
    })
    fila("💰 Costo instalación proyecto (COP)", {
        "FUN": fun.get("costo_instalacion"),
        "Costos": cos.get("costo_instalacion"),
    })

    # ---- Aritmética ----
    aritmetica = []

    ind    = af.get("individuos")
    factor = af.get("factor_reposicion") or comp.get("factor_reposicion")
    reponer = af.get("individuos_reponer") or comp.get("individuos_reponer")
    if ind and factor and reponer:
        try:
            esperado = int(float(ind)) * int(float(factor))
            real = int(float(reponer))
            ok = abs(esperado - real) <= 1
            aritmetica.append({
                "verificacion": "Factor de reposición",
                "operacion": f"{ind} árboles × factor {factor} = {esperado} esperados",
                "reportado": str(reponer),
                "ok": "✅" if ok else "❌"
            })
        except Exception:
            pass

    c_ap = cos.get("costo_aprovechamiento")
    c_co = cos.get("costo_compensacion")
    c_in = cos.get("costo_instalacion")
    if c_ap and c_co and c_in:
        try:
            total = int(c_ap) + int(c_co) + int(c_in)
            aritmetica.append({
                "verificacion": "Suma de los tres costos",
                "operacion": f"Aprov. {_fmt(c_ap)} + Comp. {_fmt(c_co)} + Instal. {_fmt(c_in)}",
                "reportado": f"= {_fmt(str(total))} COP",
                "ok": "ℹ️"
            })
        except Exception:
            pass

    return {
        "cotejo": filas_cotejo,
        "incoherencias": incoherencias,
        "aritmetica": aritmetica,
        "datos_crudos": documentos,
    }
