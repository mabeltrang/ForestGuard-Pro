"""
analyzer.py — Validador de paquetes forestales sin API de IA.
Extrae valores clave de cada documento mediante regex y los cruza
para detectar inconsistencias automáticamente.

Estructura de costos:
- Costo aprovechamiento  → Informe AF  + Doc Costos (tabla 1)
- Costo compensación     → Informe AF o Plan Compensación separado + Doc Costos (tabla 2)
- Costo instalación      → FUN + Doc Costos (tabla 3)
"""

import re


# ---------------------------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------------------------

def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.lower().strip())


def _extraer_numero(patron: str, texto: str, flags=re.IGNORECASE) -> str | None:
    m = re.search(patron, texto, flags)
    if m:
        val = m.group(1).strip()
        # Formato colombiano: 1.234.567,89 → quitar puntos de miles, coma→punto decimal
        # Detectar si hay coma decimal (último separador es coma)
        if re.search(r'\d,\d{1,2}$', val):
            val = val.replace(".", "").replace(",", ".")
        else:
            val = val.replace(",", "")
        return val
    return None


def _extraer_todos(patron: str, texto: str, flags=re.IGNORECASE) -> list:
    """Devuelve todos los grupos capturados que coincidan."""
    return [m.group(1).strip() for m in re.finditer(patron, texto, flags)]


def _extraer_texto(patron: str, texto: str, flags=re.IGNORECASE) -> str | None:
    m = re.search(patron, texto, flags)
    return m.group(1).strip() if m else None


def _limpiar_cop(val: str) -> str | None:
    """Normaliza un valor monetario COP: quita puntos de miles."""
    if not val:
        return None
    val = val.replace(".", "").replace(",", "")
    return val if val.isdigit() else None


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

    # Costo instalación en el FUN — campo "Costo del Proyecto, Obra o Actividad"
    r["costo_instalacion"] = _extraer_numero(
        r"costo\s+del\s+proyecto[,\s]+obra[^\d]{0,30}([\d\.\,]+)", texto
    ) or _extraer_numero(
        r"costo\s+del\s+proyecto[^\d]{0,30}([\d\.\,]+)", texto
    )

    r["municipio"] = _extraer_texto(
        r"municipio[:\s]+([A-Za-záéíóúÁÉÍÓÚñÑ\s]+?)(?:\n|,|departamento)", texto
    )

    r["nombre_proyecto"] = _extraer_texto(
        r"nombre\s+del\s+proyecto[:\s]+([^\n]{5,80})", texto
    ) or _extraer_texto(
        r"minigranja\s+solar\s+([A-Za-záéíóúÁÉÍÓÚñÑ\s]+?)(?:\n|\.)", texto
    )

    return r


def extraer_informe_af(texto: str) -> dict:
    """
    Extrae del Informe de Aprovechamiento Forestal.
    También puede contener el Plan de Compensación con su costo.
    """
    r = {}

    r["individuos_intro"] = _extraer_numero(
        r"aprovechamiento\s+(?:forestal\s+)?de\s+(\d{1,4})\s+[áa]rboles?", texto
    )
    r["individuos_tabla"] = _extraer_numero(
        r"total[^\d]{0,20}(\d{1,4})\s*(?:individuos?|[áa]rboles?)?", texto
    )
    r["individuos"] = r["individuos_intro"] or r["individuos_tabla"]

    r["individuos_reponer"] = _extraer_numero(
        r"(?:reposici[oó]n|compensaci[oó]n|reponer|plantar)[^\d]{0,40}(\d{1,4})\s*(?:individuos?|[áa]rboles?|pl[áa]ntulas?)", texto
    ) or _extraer_numero(
        r"(\d{1,4})\s*(?:individuos?|[áa]rboles?)\s*(?:a\s+)?(?:reponer|plantar|resembrar)", texto
    )

    r["factor_reposicion"] = _extraer_numero(
        r"factor\s+de\s+(?:reposici[oó]n|compensaci[oó]n)[^\d]{0,20}(\d{1,2})", texto
    ) or _extraer_numero(
        r"(\d{1,2})\s*[áa]rboles?\s+por\s+(?:cada\s+)?[áa]rbol\s+talado", texto
    )

    r["volumen_m3"] = _extraer_numero(
        r"(?:volumen|tala)[^\d]{0,40}([\d,\.]+)\s*m(?:3|³|etros?\s*c[uú]bicos?)", texto
    )

    r["area_ha"] = _extraer_numero(
        r"[áa]rea[^\d]{0,30}([\d,\.]+)\s*(?:hect[áa]reas?|ha\b)", texto
    )

    potencias = re.findall(r"([\d,\.]+)\s*k[Ww][Pp]?\b", texto, re.IGNORECASE)
    r["potencia_kwp"] = potencias[0].replace(",", ".") if potencias else None

    for nombre in ["afinia", "cens", "aire", "air-e", "enel", "celsia", "codensa", "epsa", "chec", "essa"]:
        if nombre in texto.lower():
            r["distribuidora"] = nombre.upper()
            break
    else:
        r["distribuidora"] = None

    # --- Costo de aprovechamiento forestal (dentro del Informe AF) ---
    r["costo_aprovechamiento"] = _extraer_numero(
        r"total[^\d]{0,40}(?:costo[s]?\s+de\s+)?aprovechamiento[^\d]{0,20}([\d\.\,]+)", texto
    ) or _extraer_numero(
        r"(?:costo[s]?\s+)?(?:total\s+)?(?:de\s+)?tala[^\d]{0,30}([\d\.\,]+)", texto
    ) or _extraer_numero(
        r"valor\s+total[^\d]{0,30}aprovechamiento[^\d]{0,20}([\d\.\,]+)", texto
    )

    # --- Costo de compensación (puede estar acá si no hay doc separado) ---
    r["costo_compensacion"] = _extraer_numero(
        r"total[^\d]{0,40}(?:costo[s]?\s+de\s+)?compensaci[oó]n[^\d]{0,20}([\d\.\,]+)", texto
    ) or _extraer_numero(
        r"total[^\d]{0,40}reposici[oó]n[^\d]{0,20}([\d\.\,]+)", texto
    ) or _extraer_numero(
        r"valor\s+total[^\d]{0,30}compensaci[oó]n[^\d]{0,20}([\d\.\,]+)", texto
    )

    r["nombre_proyecto"] = _extraer_texto(
        r"(?:informe|plan)\s+de\s+aprovechamiento[^\n]{0,100}", texto
    )

    return r


def extraer_compensacion(texto: str) -> dict:
    """
    Extrae del Plan de Compensación cuando viene como documento separado.
    """
    r = {}

    r["individuos_reponer"] = _extraer_numero(
        r"(?:reposici[oó]n|compensaci[oó]n|sembrar|plantar)[^\d]{0,40}(\d{1,4})\s*(?:individuos?|[áa]rboles?|pl[áa]ntulas?)", texto
    ) or _extraer_numero(
        r"(\d{1,4})\s*(?:individuos?|[áa]rboles?|pl[áa]ntulas?)\s*(?:a\s+)?(?:reponer|plantar|sembrar)", texto
    )

    r["factor_reposicion"] = _extraer_numero(
        r"factor\s+de\s+(?:reposici[oó]n|compensaci[oó]n)[^\d]{0,20}(\d{1,2})", texto
    )

    # Costo total de compensación — total de la tabla de costos de compensación
    r["costo_compensacion"] = _extraer_numero(
        r"total[^\d]{0,40}(?:costo[s]?\s+de\s+)?compensaci[oó]n[^\d]{0,20}([\d\.\,]+)", texto
    ) or _extraer_numero(
        r"total[^\d]{0,40}reposici[oó]n[^\d]{0,20}([\d\.\,]+)", texto
    ) or _extraer_numero(
        r"valor\s+total[^\d]{0,30}compensaci[oó]n[^\d]{0,20}([\d\.\,]+)", texto
    ) or _extraer_numero(
        r"(?:gran\s+)?total[^\d]{0,20}([\d\.\,]{6,})", texto  # fallback: primer gran total numérico
    )

    r["nombre_proyecto"] = _extraer_texto(
        r"(?:plan|programa)\s+de\s+compensaci[oó]n[^\n]{0,100}", texto
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
    r["potencia_kwp"] = potencias[0].replace(",", ".") if potencias else None

    for nombre in ["afinia", "cens", "aire", "air-e", "enel", "celsia", "codensa", "epsa", "chec", "essa"]:
        if nombre in texto.lower():
            r["distribuidora"] = nombre.upper()
            break
    else:
        r["distribuidora"] = None

    m = re.search(r"conclusi[oó]n(?:es)?[\s\S]{0,50}\n([\s\S]{50,600}?)(?:\n\n|\Z)", texto, re.IGNORECASE)
    r["conclusion"] = m.group(1).strip()[:300] if m else None

    r["nombre_proyecto"] = _extraer_texto(
        r"informe\s+(?:de\s+)?aptitud[^\n]{0,100}", texto
    )

    return r


def extraer_costos(texto: str) -> dict:
    """
    Doc de Costos y Presupuesto — tres tablas separadas con su propio subtotal.
    Tabla 1: Aprovechamiento forestal
    Tabla 2: Compensación / Reposición
    Tabla 3: Instalación del proyecto
    """
    r = {}

    r["individuos"] = _extraer_numero(
        r"aprovechamiento\s+(?:forestal\s+)?de\s+(\d{1,4})\s+[áa]rboles?", texto
    ) or _extraer_numero(
        r"(\d{1,4})\s*[áa]rboles?\s*(?:a\s+)?(?:aprovechar|talar)", texto
    )

    r["individuos_reponer"] = _extraer_numero(
        r"(?:reposici[oó]n|compensaci[oó]n)\s+de\s+(\d{1,4})\s*(?:individuos?|[áa]rboles?|pl[áa]ntulas?)", texto
    ) or _extraer_numero(
        r"(\d{1,4})\s*(?:individuos?|[áa]rboles?)\s*a\s+(?:reponer|plantar|compensar)", texto
    )

    r["volumen_m3"] = _extraer_numero(
        r"tala[^\d]{0,30}([\d,\.]+)\s*m(?:3|³)?", texto
    )

    # ---- Tabla 1: Costo de aprovechamiento ----
    # Buscar el total de la sección de aprovechamiento
    # Estrategia: encontrar la sección y luego el último total antes de la siguiente sección
    r["costo_aprovechamiento"] = _extraer_costo_seccion(
        texto,
        inicio=r"(?:costos?\s+de\s+)?aprovechamiento\s+forestal",
        fin=r"(?:costos?\s+de\s+)?(?:compensaci[oó]n|reposici[oó]n|instalaci[oó]n|implementaci[oó]n)"
    )

    # ---- Tabla 2: Costo de compensación ----
    r["costo_compensacion"] = _extraer_costo_seccion(
        texto,
        inicio=r"(?:costos?\s+de\s+)?(?:compensaci[oó]n|reposici[oó]n)",
        fin=r"(?:costos?\s+de\s+)?(?:instalaci[oó]n|implementaci[oó]n|proyecto|total\s+valor)"
    )

    # ---- Tabla 3: Costo de instalación ----
    r["costo_instalacion"] = _extraer_numero(
        r"total\s+valor\s+del\s+proyecto[^\d]{0,20}([\d\.\,]+)", texto
    ) or _extraer_costo_seccion(
        texto,
        inicio=r"(?:costos?\s+de\s+)?(?:instalaci[oó]n|implementaci[oó]n|proyecto)",
        fin=r"(?:gran\s+total|total\s+general|\Z)"
    )

    r["nombre_proyecto"] = _extraer_texto(
        r"(?:presupuesto|costos?)\s+(?:y\s+)?(?:presupuesto\s+)?(?:del\s+)?proyecto[^\n]{0,80}", texto
    )

    return r


def _extraer_costo_seccion(texto: str, inicio: str, fin: str) -> str | None:
    """
    Extrae el valor total de una sección delimitada por patrones de inicio y fin.
    Busca el último número grande (>=4 dígitos) antes del patrón fin.
    """
    m_ini = re.search(inicio, texto, re.IGNORECASE)
    if not m_ini:
        return None

    pos_ini = m_ini.start()
    texto_desde = texto[pos_ini:]

    m_fin = re.search(fin, texto_desde, re.IGNORECASE)
    segmento = texto_desde[:m_fin.start()] if m_fin else texto_desde[:3000]

    # Buscar "total" seguido de número grande en el segmento
    candidatos = re.findall(
        r"total[^\d]{0,30}([\d\.]{4,}(?:[,\d]{0,10})?)", segmento, re.IGNORECASE
    )
    if candidatos:
        val = candidatos[-1]  # el último total del segmento
        return val.replace(".", "").replace(",", "")

    # Fallback: último número grande del segmento (>=6 dígitos = al menos $100.000)
    numeros = re.findall(r"([\d\.]{6,})", segmento)
    if numeros:
        val = numeros[-1].replace(".", "")
        return val if len(val) >= 5 else None

    return None


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
    r["potencia_kwp"] = potencias[0].replace(",", ".") if potencias else None

    return r


# ---------------------------------------------------------------------------
# CLASIFICACIÓN DE TIPO DE DOCUMENTO
# ---------------------------------------------------------------------------

TIPOS = {
    "FUN": [
        "formulario único nacional", "fun", "formato único",
        "superficie (ha)", "costo del proyecto, obra"
    ],
    "INFORME_AF": [
        "informe de aprovechamiento", "plan de aprovechamiento",
        "informe forestal", "factor de reposición", "árboles aislados"
    ],
    "COMPENSACION": [
        "plan de compensación", "plan de reposición", "programa de compensación",
        "compensacion forestal", "reposicion forestal"
    ],
    "APTITUD": [
        "aptitud del suelo", "aptitud de suelo", "vocación del suelo",
        "estudio técnico", "uso del suelo"
    ],
    "COSTOS": [
        "costos y presupuesto", "presupuesto", "total valor del proyecto",
        "plan de costos", "costo total de aprovechamiento", "costo total de compensación"
    ],
    "OFICIO": [
        "solicitud de aprovechamiento forestal único",
        "cordial saludo", "se permite presentar",
        "adjunta la siguiente documentación"
    ],
}


def clasificar_documento(nombre_archivo: str, texto: str) -> str:
    nombre = nombre_archivo.lower()
    texto_n = _normalizar(texto[:3000])

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
# MOTOR DE COMPARACIÓN
# ---------------------------------------------------------------------------

def _comparar(val_a: str | None, val_b: str | None, tolerancia_pct: float = 2.0) -> bool:
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
        return val_a.strip().lower() == val_b.strip().lower()


def analizar_paquete(documentos: dict[str, dict]) -> dict:
    fun  = documentos.get("FUN", {})
    af   = documentos.get("INFORME_AF", {})
    comp = documentos.get("COMPENSACION", {})
    apt  = documentos.get("APTITUD", {})
    cos  = documentos.get("COSTOS", {})
    ofi  = documentos.get("OFICIO", {})

    # El costo de compensación puede venir del AF o del doc separado
    costo_comp_fuente = comp.get("costo_compensacion") or af.get("costo_compensacion")
    costo_comp_label  = "Plan Comp." if comp.get("costo_compensacion") else "Informe AF"

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
            "FUN": vals.get("FUN", "—") or "—",
            "Informe AF": vals.get("Informe AF", "—") or "—",
            "Plan Comp.": vals.get("Plan Comp.", "—") or "—",
            "Aptitud": vals.get("Aptitud", "—") or "—",
            "Costos": vals.get("Costos", "—") or "—",
            "Oficio": vals.get("Oficio", "—") or "—",
            "✓": consistente,
        })

        if consistente == "❌":
            incoherencias.append({
                "dato": dato,
                "valores": {k: v for k, v in vals.items() if v is not None}
            })

    # ---- Individuos ----
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

    fila("Individuos a reponer/compensar", {
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

    # ---- COSTOS — el cruce clave ----
    fila("💰 Costo aprovechamiento (COP)", {
        "Informe AF": af.get("costo_aprovechamiento"),
        "Costos": cos.get("costo_aprovechamiento"),
    })

    fila("💰 Costo compensación (COP)", {
        costo_comp_label: costo_comp_fuente,
        "Costos": cos.get("costo_compensacion"),
    })

    fila("💰 Costo instalación proyecto (COP)", {
        "FUN": fun.get("costo_instalacion"),
        "Costos": cos.get("costo_instalacion"),
    })

    # ---- Verificación aritmética ----
    aritmetica = []

    # Factor de reposición
    ind    = af.get("individuos")
    factor = af.get("factor_reposicion") or comp.get("factor_reposicion")
    reponer = af.get("individuos_reponer") or comp.get("individuos_reponer")
    if ind and factor and reponer:
        esperado = int(float(ind)) * int(float(factor))
        real = int(float(reponer))
        ok = abs(esperado - real) <= 1
        aritmetica.append({
            "verificacion": "Factor de reposición",
            "operacion": f"{ind} árboles × factor {factor} = {esperado} esperados",
            "reportado": str(reponer),
            "ok": "✅" if ok else "❌"
        })

    # Suma de los tres costos vs total en doc Costos (si se pueden sumar)
    c_ap  = cos.get("costo_aprovechamiento")
    c_co  = cos.get("costo_compensacion")
    c_in  = cos.get("costo_instalacion")
    if c_ap and c_co and c_in:
        try:
            total_calculado = int(c_ap) + int(c_co) + int(c_in)
            aritmetica.append({
                "verificacion": "Suma de los tres costos",
                "operacion": f"Aprov. {int(c_ap):,} + Comp. {int(c_co):,} + Instal. {int(c_in):,}",
                "reportado": f"= {total_calculado:,} COP",
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
