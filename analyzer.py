import re
import unicodedata

def normalize(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .strip()
    )

ZONAS_DE_VIDA_IGAC = [
    r"Bosque\s+H[uú]medo\s+(?:Tropical|Premontano|Montano\s+Bajo|Montano|Subandino)",
    r"Bosque\s+Seco\s+Tropical",
    r"Bosque\s+Muy\s+H[uú]medo\s+(?:Tropical|Premontano|Montano\s+Bajo|Montano)",
    r"Bosque\s+Pluvial\s+(?:Premontano|Montano|Subandino)",
    r"Bosque\s+Muy\s+Seco\s+Tropical",
    r"Matorral\s+Desértico\s+(?:Tropical|Premontano)",
    r"Monte\s+Espinoso\s+(?:Tropical|Premontano)",
    r"Páramo",
    r"Selva\s+(?:H[uú]meda|Tropical|Pluvial)",
    r"\b(?:bh|bs|bmh|bp|bms|md|me|p)\s*[-–]\s*[A-Z][A-Za-z]+\b",
]

def _get_context(text: str, start_pos: int, end_pos: int, window=80) -> str:
    prefix = text[max(0, start_pos - 1200):start_pos]
    items = re.findall(r"(?:\b|\n)(?:\d+\.){1,3}\d+\b", prefix)
    last_item = items[-1] if items else ""
    
    snippet_start = max(0, start_pos - window)
    snippet_end = min(len(text), end_pos + window)
    snippet = text[snippet_start:snippet_end].replace("\n", " | ").strip()
    
    if last_item:
        return f"[Ítem {last_item}] ...{snippet}..."
    return f"...{snippet}..."

def _find_zona_vida(text: str):
    for pat in ZONAS_DE_VIDA_IGAC:
        m = re.search(pat, text, re.IGNORECASE)
        if m: 
            return m.group(0).strip(), _get_context(text, m.start(), m.end())

    m = re.search(
        r"(?i)zona\s+de\s+vida\s*(?:afectada|afectado)?\s*[:\-=]\s*"
        r"(?!afectad)([A-Za-záéíóúÁÉÍÓÚ][A-Za-záéíóúÁÉÍÓÚ\s\-]+?)(?=\r?\n|[.,;(]|\d)",
        text,
    )
    if m:
        val = m.group(1).strip()
        if normalize(val) not in ("afectada", "afectado", "afectadas", "afectados"):
            return val, _get_context(text, m.start(), m.end())
    return None, None

def _find_area(text: str, filename: str = ""):
    # Exclude documents about waste, social, or unrelated management
    if any(x in filename.lower() for x in ["residuos", "social", "gestion", "nomina", "asistencia"]):
        return None, None

    patterns = [
        r"(?i)[aá]rea\s+de\s+(?:intervenci[oó]n|proyecto|afectaci[oó]n|estudio)[^.\n]{0,50}?([\d]+[,.]?\d+)\s*(?:ha\b|hect[aá]reas?)(?!\s*%)",
        r"(?i)[aá]rea[^.\n]{0,80}?([\d]+[,.]?\d+)\s*(?:ha\b|hect[aá]reas?)(?!\s*%)",
        r"(?i)superficie[^.\n]{0,80}?([\d]+[,.]?\d+)\s*(?:ha\b|hect[aá]reas?)(?!\s*%)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip().strip(".,;:- ")
            if val and val != "100": 
                return val, _get_context(text, m.start(), m.end())
    return None, None
def _find_municipio(text: str, filename: str = ""):
    # Exclude administrative documents that usually contain corporate addresses
    if any(x in filename.lower() for x in ["camara", "comercio", "rut", "nit", "cedula", "representacion"]):
        return None, None

    patterns = [
        r"(?i)municipio\s+de\s+([A-ZÁÉÍÓÚ][a-zA-ZáéíóúÁÉÍÓÚ]+(?:\s+[A-ZÁÉÍÓÚ][a-zA-ZáéíóúÁÉÍÓÚ]+){0,2})(?=\r?\n|[,;.\-\(])",
        r"(?i)(?:ubicado|localizado|localizada|ubicada)\s+en\s+el\s+municipio\s+de\s+([A-ZÁÉÍÓÚ][a-zA-ZáéíóúÁÉÍÓÚ]+(?:\s+[A-ZÁÉÍÓÚ][a-zA-ZáéíóúÁÉÍÓÚ]+){0,2})(?=\r?\n|[,;.\-])",
        r"(?i)municipio[:\s]+([A-ZÁÉÍÓÚ][a-zA-ZáéíóúÁÉÍÓÚ]+(?:\s+[A-ZÁÉÍÓÚ][a-zA-ZáéíóúÁÉÍÓÚ]+){0,2})(?=\r?\n|[,;.\-])",
    ]
    invalid_words = {"predio", "propiedad", "privad", "lote", "finca", "vereda", "domicilio", "notaria"}
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip()
            if len(val.split()) <= 3 and not any(p in normalize(val) for p in invalid_words):
                return val, _get_context(text, m.start(), m.end())
    return None, None

COST_CATEGORIES = {
    "Costo Compensación": [
        r"(?i)(?:compensaci[oó]n|plan\s+de\s+compensaci[oó]n)[^\d\n]{0,60}(?:\$|pesos|COP)\s*([\d\.,]{5,})", 
        r"(?i)valor\s+(?:de\s+la\s+)?compensaci[oó]n[^\d\n]{0,40}(?:\$|pesos|COP)\s*([\d\.,]{5,})",
    ],
    "Costo Aprovechamiento": [
        r"(?i)(?:aprovechamiento\s+forestal?|derecho\s+de\s+aprovechamiento)[^\d\n]{0,60}(?:\$|pesos|COP)\s*([\d\.,]{5,})",
    ],
    "Costo FUN / Instalación": [
        r"(?i)(?:instalaci[oó]n|FUN|formulario\s+[uú]nico\s+nacional)[^\d\n]{0,60}(?:\$|pesos|COP)\s*([\d\.,]{5,})",
    ],
    "Costo Total": [
        # Priorizar "Gran Total" o similar con signo de pesos
        r"(?i)(?:gran\s+total|total\s+a\s+pagar|total\s+del\s+proyecto|costo\s+del\s+proyecto)[^\d\n]{0,60}(?:\$|pesos|COP)\s*([\d\.,]{6,})",
        # Buscar "Total" solo si tiene símbolo de moneda
        r"(?i)total\s*[:\-=]?\s*(?:\$|pesos|COP)\s*([\d\.,]{6,})",
        r"(?i)presupuesto\s*[:\-=]\s*(?:\$|pesos|COP)\s*([\d\.,]{6,})",
    ],
}

BASE_FIELDS = {
    "Número de Individuos": [
        # 1. Prioridad máxima: Totales explícitos en tablas (especie: total | ... : 8)
        r"(?i)especie:\s*total[^\d\n]{0,60}com[uú]n:\s*(\d+)\b",
        r"(?i)(?:total|suma|gran\s+total)\s*(?:de\s+)?(?:individuos|[aá]rboles)[^\d\n]{0,30}\b(\d+)\b",
        
        # 2. Búsqueda específica evitando citas legales (Decreto, Parte, Título)
        r"(?i)(?<!parte\s)(?<!t[ií]tulo\s)(?<!cap[ií]tulo\s)(?<!secci[oó]n\s)(?<!decreto\s)n[uú]mero\s+de\s+individuos[^\d\n]{0,20}\b(\d+)\b",
        
        # 3. Genérico pero con exclusiones fuertes
        r"(?i)(?<!especies\s)(?<!especie\s)(?<!art[ií]culo\s)(?:individuos|[aá]rboles|ejemplares)[^\d\n]{0,40}\b(\d+)\b(?!\s*(?:m3|m³|ha\b|%))",
    ],
    "Volumen (m³)": [
        r"(?i)volumen\s*(?:total|maderable|en\s+pie|comercial|aprovechable)?\s*[:\-=]?\s*([\d\.,]+)\s*(?:m3|m³|metros?\s*c[uú]bicos?)",
        r"(?i)\bVTA\b\s*[:\-=]?\s*([\d\.,]+)",
        r"(?i)volumen[^\d\n]{0,30}([\d\.,]+)\s*(?:m3|m³)",
    ],
}

def _find_first_with_context(patterns: list, text: str, is_cost=False):
    all_candidates = []
    
    for pat in patterns:
        for m in re.finditer(pat, text):
            val = m.group(1).strip().strip(".,;:- ")
            if not val: continue
            
            # Context for filtering
            ctx_start = max(0, m.start() - 60)
            ctx_end = min(len(text), m.end() + 60)
            local_ctx = text[ctx_start:ctx_end].lower()

            if is_cost:
                # 1. Mandatory currency indicator or "Valor" in context
                if not any(x in local_ctx for x in ["$", "pesos", "cop", "valor", "total"]):
                    continue
                # 2. Avoid version numbers (2.2.1)
                if val.count('.') > 1 and ',' not in val:
                    continue
                # 3. Avoid volume units
                if any(x in local_ctx[60:75] for x in ["m3", "m³", "ha"]):
                    continue
                
                num_only = re.sub(r'[^\d]', '', val)
                if len(num_only) < 4: continue
                all_candidates.append({
                    "val": val, 
                    "num": int(num_only), 
                    "ctx": _get_context(text, m.start(), m.end()),
                    "priority": 2 if "$" in local_ctx else 1
                })
            else:
                # For Individuals:
                # 1. Avoid legal citations
                if any(x in local_ctx for x in ["decreto", "parte", "titulo", "seccion", "articulo", "ley"]):
                    # If it contains these words BUT also "total", maybe it's valid, but let's be safe
                    if "total" not in local_ctx:
                        continue
                
                num_only = re.sub(r'[^\d]', '', val)
                if not num_only.isdigit(): continue
                
                all_candidates.append({
                    "val": val, 
                    "num": int(num_only), 
                    "ctx": _get_context(text, m.start(), m.end()),
                    "priority": 2 if "total" in local_ctx else 1
                })
            
    if not all_candidates:
        return None, None
        
    # Sort by priority, then by value (descending to get the "Total")
    all_candidates.sort(key=lambda x: (x["priority"], x["num"]), reverse=True)
    best = all_candidates[0]
    return best["val"], best["ctx"]

def classify_doc(filename: str) -> str:
    fn = filename.lower()
    if "costo" in fn or "presupuesto" in fn: return "MASTER_COSTOS"
    if "compensacion" in fn: return "COMPENSACION"
    if "aprovechamiento" in fn: return "APROVECHAMIENTO"
    if "fun" in fn: return "FUN"
    return "UNKNOWN"

def analyze_reports(extracted_data: list) -> dict:
    report_findings: dict = {}
    raw_texts: dict = {}
    doc_types: dict = {}

    for item in extracted_data:
        text = item["text"]
        fname = item["filename"]
        raw_texts[fname] = text
        doc_types[fname] = classify_doc(fname)
        fields = {}

        v, c = _find_zona_vida(text)
        fields["Zona de Vida"] = {"value": v, "context": c}
        v, c = _find_area(text, fname)
        fields["Área (ha)"] = {"value": v, "context": c}
        v, c = _find_municipio(text, fname)
        fields["Municipio"] = {"value": v, "context": c}

        for field, patterns in BASE_FIELDS.items():
            v, c = _find_first_with_context(patterns, text, is_cost=False)
            fields[field] = {"value": v, "context": c}

        for cat, patterns in COST_CATEGORIES.items():
            v, c = _find_first_with_context(patterns, text, is_cost=True)
            fields[cat] = {"value": v, "context": c}

        report_findings[fname] = fields

    inconsistencies = []
    
    # 1. Cross-Document Cost Validation (The "Smart" part)
    master_file = next((f for f, t in doc_types.items() if t == "MASTER_COSTOS"), None)
    if master_file:
        master = report_findings[master_file]
        
        # Check Aprovechamiento
        aprov_file = next((f for f, t in doc_types.items() if t == "APROVECHAMIENTO"), None)
        if aprov_file:
            v_master = master["Costo Aprovechamiento"]["value"]
            v_doc = report_findings[aprov_file]["Costo Total"]["value"]
            if v_master and v_doc and normalize(v_master) != normalize(v_doc):
                inconsistencies.append({
                    "campo": "Costo Aprovechamiento",
                    "tipo": "conflicto",
                    "mensaje": f"'{master_file}' (Presupuesto) → '{v_master}' ({master['Costo Aprovechamiento']['context']}) | '{aprov_file}' (Valor Real) → '{v_doc}' ({report_findings[aprov_file]['Costo Total']['context']})"
                })

        # Check Compensacion
        comp_file = next((f for f, t in doc_types.items() if t == "COMPENSACION"), None)
        if comp_file:
            v_master = master["Costo Compensación"]["value"]
            v_doc = report_findings[comp_file]["Costo Total"]["value"]
            if v_master and v_doc and normalize(v_master) != normalize(v_doc):
                inconsistencies.append({
                    "campo": "Costo Compensación",
                    "tipo": "conflicto",
                    "mensaje": f"'{master_file}' (Presupuesto) → '{v_master}' ({master['Costo Compensación']['context']}) | '{comp_file}' (Valor Real) → '{v_doc}' ({report_findings[comp_file]['Costo Total']['context']})"
                })

        # Check FUN / Instalacion
        fun_file = next((f for f, t in doc_types.items() if t == "FUN"), None)
        if fun_file:
            v_master = master["Costo FUN / Instalación"]["value"]
            v_doc = report_findings[fun_file]["Costo Total"]["value"]
            if v_master and v_doc and normalize(v_master) != normalize(v_doc):
                inconsistencies.append({
                    "campo": "Costo FUN / Instalación",
                    "tipo": "conflicto",
                    "mensaje": f"'{master_file}' (Presupuesto) → '{v_master}' ({master['Costo FUN / Instalación']['context']}) | '{fun_file}' (Valor Real) → '{v_doc}' ({report_findings[fun_file]['Costo Total']['context']})"
                })

    # 2. General Equality Validation (for things that MUST be the same everywhere)
    for field in ["Municipio", "Número de Individuos", "Zona de Vida"]:
        found_in = {
            fname: report_findings[fname][field]["value"]
            for fname in report_findings
            if report_findings[fname][field]["value"] is not None
        }
        if len(found_in) < 2: continue
        valores = list(found_in.values())
        if len(set(normalize(v) for v in valores)) > 1:
            partes = []
            for fn, vl in found_in.items():
                ctx = report_findings[fn][field]["context"] or ""
                partes.append(f"'{fn}' → '{vl}' ({ctx})")
            
            inconsistencies.append({
                "campo": field,
                "tipo": "conflicto",
                "mensaje": " | ".join(partes),
            })

    findings_display = {}
    for fname, flds in report_findings.items():
        findings_display[fname] = {
            k: {
                "val": (v["value"] if v["value"] is not None else "—"),
                "ctx": v["context"]
            } for k, v in flds.items()
        }

    count = len(inconsistencies)
    return {
        "findings": findings_display,
        "inconsistencies": inconsistencies,
        "raw_texts": raw_texts,
        "status": "error" if inconsistencies else "success",
        "message": (
            f"Se encontraron {count} inconsistencias."
            if inconsistencies
            else "✅ Validación exitosa."
        ),
    }
