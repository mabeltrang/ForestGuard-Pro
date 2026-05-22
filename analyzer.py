"""
analyzer.py — Validador de paquetes forestales sin API de IA.
Extrae valores clave de cada documento mediante regex y los cruza
para detectar inconsistencias automáticamente.
"""

import re


# ---------------------------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------------------------

def _normalizar(texto: str) -> str:
    """Convierte a minúsculas y normaliza espacios para búsquedas robustas."""
    return re.sub(r"\s+", " ", texto.lower().strip())


def _extraer_numero(patron: str, texto: str, flags=re.IGNORECASE) -> str | None:
    """Devuelve el primer grupo numérico que coincida con el patrón."""
    m = re.search(patron, texto, flags)
    if m:
        # Normalizar separadores decimales colombianos (coma → punto)
        return m.group(1).replace(".", "").replace(",", ".")
    return None


def _extraer_texto(patron: str, texto: str, flags=re.IGNORECASE) -> str | None:
    m = re.search(patron, texto, flags)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# EXTRACCIÓN DE VALORES POR TIPO DE DOCUMENTO
# ---------------------------------------------------------------------------

def extraer_fun(texto: str) -> dict:
    """Extrae valores del Formulario Único Nacional."""
    r = {}

    # Individuos: buscar "Cantidad Total" seguido de número
    r["individuos"] = _extraer_numero(
        r"cantidad\s+total[^\d]{0,30}(\d{1,4})", texto
    )

    # Volumen m³
    r["volumen_m3"] = _extraer_numero(
        r"cantidad\s+total[^\d]{0,80}([\d,\.]+)\s*m(?:etros?\s*c[uú]bicos?|3|³)", texto
    ) or _extraer_numero(
        r"([\d,\.]+)\s*m(?:etros?\s*c[uú]bicos?|3|³)\s*de\s*volumen", texto
    )

    # Área del predio
    r["area_ha"] = _extraer_numero(
        r"superficie\s*\(ha\)[^\d]{0,20}([\d,\.]+)", texto
    ) or _extraer_numero(
        r"[áa]rea[^\d]{0,30}([\d,\.]+)\s*ha", texto
    )

    # Costo del proyecto
    r["costo_proyecto"] = _extraer_numero(
        r"costo\s+del\s+proyecto[^\d]{0,30}([\d\.\,]+)", texto
    )

    # Municipio
    r["municipio"] = _extraer_texto(
        r"municipio[:\s]+([A-Za-záéíóúÁÉÍÓÚñÑ\s]+?)(?:\n|,|departamento)", texto
    )

    # Nombre del proyecto
    r["nombre_proyecto"] = _extraer_texto(
        r"nombre\s+del\s+proyecto[:\s]+([^\n]{5,80})", texto
    ) or _extraer_texto(
        r"minigranja\s+solar\s+([A-Za-záéíóúÁÉÍÓÚñÑ\s]+?)(?:\n|\.)", texto
    )

    return r


def extraer_informe_af(texto: str) -> dict:
    """Extrae valores del Informe de Aprovechamiento Forestal."""
    r = {}

    # Individuos en introducción
    r["individuos_intro"] = _extraer_numero(
        r"aprovechamiento\s+(?:forestal\s+)?de\s+(\d{1,4})\s+[áa]rboles?", texto
    )

    # Individuos en tabla resumen (fila Total)
    r["individuos_tabla"] = _extraer_numero(
        r"total[^\d]{0,20}(\d{1,4})\s*(?:individuos?|[áa]rboles?)?", texto
    )

    # Usar el más confiable (intro tiene prioridad)
    r["individuos"] = r["individuos_intro"] or r["individuos_tabla"]

    # Individuos a reponer
    r["individuos_reponer"] = _extraer_numero(
        r"(?:reposici[oó]n|reponer|plantar)[^\d]{0,40}(\d{1,4})\s*(?:individuos?|[áa]rboles?|pl[áa]ntulas?)", texto
    ) or _extraer_numero(
        r"(\d{1,4})\s*(?:individuos?|[áa]rboles?)\s*(?:a\s+)?(?:reponer|plantar|resembrar)", texto
    )

    # Factor de reposición
    r["factor_reposicion"] = _extraer_numero(
        r"factor\s+de\s+reposici[oó]n[^\d]{0,20}(\d{1,2})", texto
    ) or _extraer_numero(
        r"(\d{1,2})\s*[áa]rboles?\s+por\s+(?:cada\s+)?[áa]rbol\s+talado", texto
    )

    # Volumen
    r["volumen_m3"] = _extraer_numero(
        r"(?:volumen|tala)[^\d]{0,40}([\d,\.]+)\s*m(?:3|³|etros?\s*c[uú]bicos?)", texto
    )

    # Área
    r["area_ha"] = _extraer_numero(
        r"[áa]rea[^\d]{0,30}([\d,\.]+)\s*(?:hect[áa]reas?|ha\b)", texto
    )

    # Potencia AC — buscar en introducción y descripción por separado
    potencias = re.findall(
        r"([\d,\.]+)\s*k[Ww][Pp]?\b", texto, re.IGNORECASE
    )
    r["potencia_kwp"] = potencias[0].replace(",", ".") if potencias else None
    r["potencia_kwp_2"] = potencias[1].replace(",", ".") if len(potencias) > 1 else None

    # Distribuidora
    for nombre in ["afinia", "cens", "aire", "air-e", "enel", "celsia", "codensa", "epsa", "chec", "essa"]:
        if nombre in texto.lower():
            r["distribuidora"] = nombre.upper()
            break
    else:
        r["distribuidora"] = None

    # Nombre del proyecto (título del documento)
    r["nombre_proyecto"] = _extraer_texto(
        r"informe\s+de\s+aprovechamiento[^\n]{0,100}", texto
    )

    return r


def extraer_aptitud_suelo(texto: str) -> dict:
    """Extrae valores del Informe de Aptitud del Suelo."""
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

    # Conclusión
    m = re.search(r"conclusi[oó]n(?:es)?[\s\S]{0,50}\n([\s\S]{50,600}?)(?:\n\n|\Z)", texto, re.IGNORECASE)
    r["conclusion"] = m.group(1).strip()[:300] if m else None

    r["nombre_proyecto"] = _extraer_texto(
        r"informe\s+(?:de\s+)?aptitud[^\n]{0,100}", texto
    )

    return r


def extraer_costos(texto: str) -> dict:
    """Extrae valores del Documento de Costos y Presupuesto."""
    r = {}

    # Individuos a aprovechar (párrafo introductorio)
    r["individuos"] = _extraer_numero(
        r"aprovechamiento\s+(?:forestal\s+)?de\s+(\d{1,4})\s+[áa]rboles?", texto
    ) or _extraer_numero(
        r"(\d{1,4})\s*[áa]rboles?\s*(?:a\s+)?(?:aprovechar|talar)", texto
    )

    # Individuos a reponer
    r["individuos_reponer"] = _extraer_numero(
        r"reposici[oó]n\s+de\s+(\d{1,4})\s*(?:individuos?|[áa]rboles?|pl[áa]ntulas?)", texto
    ) or _extraer_numero(
        r"(\d{1,4})\s*(?:individuos?|[áa]rboles?)\s*a\s+(?:reponer|plantar)", texto
    )

    # Volumen (fila Tala)
    r["volumen_m3"] = _extraer_numero(
        r"tala[^\d]{0,30}([\d,\.]+)\s*m(?:3|³)?", texto
    )

    # Costos — buscar patrones de totales
    r["costo_aprovechamiento"] = _extraer_numero(
        r"total[^\d]{0,30}aprovechamiento[^\d]{0,30}([\d\.\,]+)", texto
    ) or _extraer_numero(
        r"total\s+(?:costo\s+)?(?:de\s+)?(?:tala|aprovechamiento)[^\d]{0,20}([\d\.\,]+)", texto
    )

    r["costo_reposicion"] = _extraer_numero(
        r"total[^\d]{0,30}(?:reposici[oó]n|compensaci[oó]n)[^\d]{0,30}([\d\.\,]+)", texto
    ) or _extraer_numero(
        r"total\s+(?:costo\s+)?(?:de\s+)?reposici[oó]n[^\d]{0,20}([\d\.\,]+)", texto
    )

    r["costo_proyecto"] = _extraer_numero(
        r"total\s+valor\s+del\s+proyecto[^\d]{0,20}([\d\.\,]+)", texto
    ) or _extraer_numero(
        r"total\s+(?:del\s+)?proyecto[^\d]{0,20}([\d\.\,]+)", texto
    )

    r["nombre_proyecto"] = _extraer_texto(
        r"(?:presupuesto|costos?)[^\n]{0,100}", texto
    )

    return r


def extraer_oficio(texto: str) -> dict:
    """Extrae valores del Oficio de Solicitud."""
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
        "formulario único nacional", "fun", "solicitud de aprovechamiento",
        "formato único", "superficie (ha)"
    ],
    "INFORME_AF": [
        "informe de aprovechamiento", "plan de aprovechamiento",
        "informe forestal", "reposición forestal", "factor de reposición"
    ],
    "APTITUD": [
        "aptitud del suelo", "aptitud de suelo", "uso del suelo",
        "vocación del suelo", "estudio técnico"
    ],
    "COSTOS": [
        "costos y presupuesto", "presupuesto", "costo total",
        "total valor del proyecto", "plan de costos"
    ],
    "OFICIO": [
        "solicitud de aprovechamiento forestal único",
        "cordial saludo", "se permite presentar",
        "adjunta la siguiente documentación"
    ],
}


def clasificar_documento(nombre_archivo: str, texto: str) -> str:
    nombre = nombre_archivo.lower()
    texto_n = _normalizar(texto[:3000])  # Solo primeras 3000 chars para clasificar

    puntajes = {tipo: 0 for tipo in TIPOS}

    for tipo, palabras_clave in TIPOS.items():
        for p in palabras_clave:
            if p in nombre:
                puntajes[tipo] += 3  # El nombre del archivo pesa más
            if p in texto_n:
                puntajes[tipo] += 1

    mejor = max(puntajes, key=puntajes.get)
    return mejor if puntajes[mejor] > 0 else "DESCONOCIDO"


# ---------------------------------------------------------------------------
# MOTOR DE COMPARACIÓN
# ---------------------------------------------------------------------------

def _comparar(val_a: str | None, val_b: str | None, tolerancia_pct: float = 2.0) -> bool:
    """
    Compara dos valores string que representan números.
    Permite tolerancia del 2% para diferencias de redondeo.
    """
    if val_a is None or val_b is None:
        return True  # No se puede comparar si falta uno
    try:
        a = float(val_a)
        b = float(val_b)
        if a == 0 and b == 0:
            return True
        diff_pct = abs(a - b) / max(abs(a), abs(b)) * 100
        return diff_pct <= tolerancia_pct
    except ValueError:
        # Comparación de strings
        return val_a.strip().lower() == val_b.strip().lower()


def analizar_paquete(documentos: dict[str, dict]) -> dict:
    """
    documentos: {tipo: {valores extraídos}}
    Retorna: {cotejo: [...filas...], incoherencias: [...], aritmetica: [...]}
    """
    fun = documentos.get("FUN", {})
    af = documentos.get("INFORME_AF", {})
    apt = documentos.get("APTITUD", {})
    cos = documentos.get("COSTOS", {})
    ofi = documentos.get("OFICIO", {})

    filas_cotejo = []
    incoherencias = []

    def fila(dato, vals: dict):
        """vals = {doc_label: valor_string_o_None}"""
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
            "Aptitud Suelo": vals.get("Aptitud Suelo", "—") or "—",
            "Costos": vals.get("Costos", "—") or "—",
            "Oficio": vals.get("Oficio", "—") or "—",
            "consistente": consistente,
        })

        if consistente == "❌":
            incoherencias.append({
                "dato": dato,
                "valores": {k: v for k, v in vals.items() if v is not None}
            })

    # ---- Filas del cotejo ----
    fila("Individuos a aprovechar", {
        "FUN": fun.get("individuos"),
        "Informe AF": af.get("individuos"),
        "Aptitud Suelo": apt.get("individuos"),
        "Costos": cos.get("individuos"),
        "Oficio": ofi.get("individuos"),
    })

    fila("Volumen aprovechamiento (m³)", {
        "FUN": fun.get("volumen_m3"),
        "Informe AF": af.get("volumen_m3"),
        "Costos": cos.get("volumen_m3"),
    })

    fila("Individuos a reponer", {
        "Informe AF": af.get("individuos_reponer"),
        "Costos": cos.get("individuos_reponer"),
    })

    fila("Área del predio (ha)", {
        "FUN": fun.get("area_ha"),
        "Informe AF": af.get("area_ha"),
        "Aptitud Suelo": apt.get("area_ha"),
    })

    fila("Potencia del proyecto (kWp)", {
        "Informe AF": af.get("potencia_kwp"),
        "Aptitud Suelo": apt.get("potencia_kwp"),
        "Oficio": ofi.get("potencia_kwp"),
    })

    fila("Empresa distribuidora", {
        "Informe AF": af.get("distribuidora"),
        "Aptitud Suelo": apt.get("distribuidora"),
        "Oficio": ofi.get("distribuidora"),
    })

    fila("Costo instalación proyecto (COP)", {
        "FUN": fun.get("costo_proyecto"),
        "Costos": cos.get("costo_proyecto"),
    })

    fila("Costo aprovechamiento (COP)", {
        "Costos": cos.get("costo_aprovechamiento"),
    })

    fila("Costo reposición/compensación (COP)", {
        "Costos": cos.get("costo_reposicion"),
    })

    # ---- Verificación aritmética ----
    aritmetica = []

    # Factor de reposición
    ind = af.get("individuos")
    factor = af.get("factor_reposicion")
    reponer_af = af.get("individuos_reponer")
    if ind and factor and reponer_af:
        esperado = int(float(ind)) * int(float(factor))
        real = int(float(reponer_af))
        ok = abs(esperado - real) <= 1
        aritmetica.append({
            "verificacion": "Factor de reposición",
            "operacion": f"{ind} árboles × factor {factor} = {esperado} esperados",
            "reportado": reponer_af,
            "ok": "✅" if ok else "❌"
        })

    return {
        "cotejo": filas_cotejo,
        "incoherencias": incoherencias,
        "aritmetica": aritmetica,
        "datos_crudos": documentos,
    }
