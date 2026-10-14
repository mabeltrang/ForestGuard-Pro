"""
epifitas.py — Lectura del Informe de caracterización de epífitas (EP) y de su
base de datos en Excel (BD), más dos datos que comparten casi todos los
documentos del paquete: bioma y zona de vida.

El dato clave que sale de aquí es cuántos árboles del inventario son
forófitos, es decir, en cuántos se encontraron epífitas de verdad. No
siempre son todos: en Gamarra Norte T26 fueron 8 de 9.
"""

import io
import re
import unicodedata
import zipfile

import pandas as pd


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _num(s) -> float | None:
    """'6.909' (miles con punto) -> 6909 ; '1.408' (decimal) se resuelve por contexto
    en quien llama. Aquí: quita separador de miles si hay 3 dígitos tras el punto
    y el número no tiene coma decimal."""
    if s is None:
        return None
    s = str(s).strip().replace("\u00a0", "")
    s = re.sub(r"[^\d.,\-]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _entero(v) -> str | None:
    return None if v is None else str(int(round(v)))


def _sin_tildes(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def excel_saneado(origen) -> io.BytesIO:
    """Algunos Excel (sobre todo los guardados con WPS) traen un autofiltro
    con un rango inválido (A1:XFD880) y openpyxl/pandas se niegan a abrirlos.
    Se copia el archivo en memoria quitando los <autoFilter>, que no afectan
    los datos."""
    datos = origen.read() if hasattr(origen, "read") else open(origen, "rb").read()
    zin = zipfile.ZipFile(io.BytesIO(datos))
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            contenido = zin.read(info.filename)
            if info.filename.startswith("xl/worksheets/") and info.filename.endswith(".xml"):
                contenido = re.sub(rb"<autoFilter\b[^>]*/>|<autoFilter\b[^>]*>.*?</autoFilter>",
                                   b"", contenido, flags=re.S)
            zout.writestr(info, contenido)
    salida.seek(0)
    return salida


# ---------------------------------------------------------------------------
# Datos comunes a varios documentos
# ---------------------------------------------------------------------------

_PATRON_BIOMA = re.compile(
    r"\b((?:zono|helo|pedo|oro|peino|lito)biomas?\b[^\n.;:()]{3,110}?)(?=\s*[.;:\n(]|$)",
    re.IGNORECASE,
)
_PATRON_ZONA_VIDA = re.compile(
    r"zona\s+de\s+vida[^()\n]{0,90}?\(\s*([a-z]{1,3}\s*-\s*[a-z]{1,3})\s*\)",
    re.IGNORECASE,
)


def extraer_comunes(texto: str) -> dict:
    """Bioma y zona de vida (abreviatura Holdridge, ej. bs-T)."""
    r = {"bioma": None, "zona_vida": None}
    if not texto:
        return r
    m = _PATRON_BIOMA.search(texto)
    if m:
        r["bioma"] = re.sub(r"\s+", " ", m.group(1)).strip(" ,")
    m = _PATRON_ZONA_VIDA.search(texto)
    if m:
        # bs-T, bh-PM: minúsculas antes del guion, mayúsculas después
        a, b = re.sub(r"\s+", "", m.group(1)).split("-", 1)
        r["zona_vida"] = f"{a.lower()}-{b.upper()}"
    return r


# ---------------------------------------------------------------------------
# Informe de caracterización de epífitas (Word / PDF)
# ---------------------------------------------------------------------------

def _filas_tabla(texto: str, columna_clave: str) -> list[dict]:
    """Las tablas del Word llegan como 'Columna: valor | Columna: valor'.
    Devuelve las filas que tienen la columna pedida."""
    filas = []
    for linea in texto.splitlines():
        if columna_clave.lower() not in linea.lower() or ":" not in linea:
            continue
        fila = {}
        for celda in linea.split(" | "):
            if ":" in celda:
                k, v = celda.split(":", 1)
                fila[k.strip()] = v.strip()
        if any(columna_clave.lower() in k.lower() for k in fila):
            filas.append(fila)
    return filas


def _col(fila: dict, *claves) -> str | None:
    for k, v in fila.items():
        kk = _sin_tildes(k.lower())
        if all(_sin_tildes(c.lower()) in kk for c in claves):
            return v
    return None


def _es_total(fila: dict) -> bool:
    return any(str(v).strip().lower().startswith("total") for v in list(fila.values())[:2])


def extraer_epifitas_informe(texto: str) -> dict:
    r = {}
    # Tabla resumen: cobertura | árboles con influencia | forófitos muestreados | spp ENoV | spp EV
    filas = [f for f in _filas_tabla(texto, "Forófitos muestreados") if not _es_total(f)]
    if filas:
        def suma(*claves):
            vals = [_num(_col(f, *claves)) for f in filas]
            vals = [v for v in vals if v is not None]
            return _entero(sum(vals)) if vals else None
        r["arboles_influencia"] = suma("arboles", "influencia") or suma("individuos")
        r["forofitos"] = suma("forofitos")
        r["coberturas"] = ", ".join(dict.fromkeys(
            v for v in (_col(f, "nombre", "cobertura") or _col(f, "cobertura") for f in filas) if v))
        # especies por grupo: se toma el máximo, no la suma (una especie puede estar en varias coberturas)
        enov = [_num(_col(f, "enov")) for f in filas]
        ev = [_num(_col(f, "spp ev")) for f in filas]
        r["spp_enov_tabla"] = _entero(max([v for v in enov if v is not None], default=None)) if any(v is not None for v in enov) else None
        r["spp_ev_tabla"] = _entero(max([v for v in ev if v is not None], default=None)) if any(v is not None for v in ev) else None

    m = re.search(r"registraron\s+(\d{1,4})\s+especies\s+de\s+ep[ií]fitas\s+no\s+vasculares", texto, re.I)
    r["spp_enov"] = m.group(1) if m else r.get("spp_enov_tabla")
    if re.search(r"no\s+se\s+registraron\s+ep[ií]fitas\s+vasculares", texto, re.I):
        r["spp_ev"] = "0"
    else:
        m = re.search(r"registraron\s+(\d{1,4})\s+especies\s+de\s+ep[ií]fitas\s+vasculares", texto, re.I)
        r["spp_ev"] = m.group(1) if m else r.get("spp_ev_tabla")

    m = re.search(r"cobertura\s+total\s+de\s+([\d.,]+)\s*cm", texto, re.I)
    if m:
        # en estos informes el punto es separador de miles: 6.909 cm² = 6909
        r["cobertura_cm2"] = _entero(_num(m.group(1).replace(".", "")))

    m = re.search(r"Representatividad\s*:\s*([\d.,]+)\s*%", texto) or \
        re.search(r"completitud\s+del\s+([\d.,]+)\s*%", texto, re.I)
    r["representatividad_pct"] = _num(m.group(1)) if m else None

    area = [_num(_col(f, "area a intervenir")) for f in _filas_tabla(texto, "intervenir (ha)") if not _es_total(f)]
    area = [a for a in area if a is not None]
    r["area_intervenir_ha"] = round(sum(area), 4) if area else None

    m = re.search(r"municipio\s+(?:de\s+)?([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,2})", texto)
    r["municipio"] = m.group(1) if m else None
    return r


# ---------------------------------------------------------------------------
# Base de datos de epífitas (Excel de campo)
# ---------------------------------------------------------------------------

def _buscar_col(columnas, *claves, excluir=()):
    for c in columnas:
        cc = _sin_tildes(str(c).lower())
        if all(_sin_tildes(k) in cc for k in claves) and not any(_sin_tildes(e) in cc for e in excluir):
            return c
    return None


def leer_bd_epifitas(origen) -> dict:
    """Cuenta forófitos con epífitas, especies y cobertura desde la BD de campo."""
    hojas = pd.read_excel(excel_saneado(origen), sheet_name=None)
    df = None
    for h in hojas.values():
        if _buscar_col(h.columns, "epifita") and _buscar_col(h.columns, "forofito"):
            df = h.dropna(how="all")
            break
    if df is None:
        return {}

    c_forofito = (_buscar_col(df.columns, "id cob", "muest") or _buscar_col(df.columns, "id_parcela")
                  or _buscar_col(df.columns, "parcela"))
    c_especie = _buscar_col(df.columns, "epifita", "especie")
    c_tipo = _buscar_col(df.columns, "tipo_org") or _buscar_col(df.columns, "dom_tipo")
    c_cm2 = _buscar_col(df.columns, "cm2")
    c_ind = _buscar_col(df.columns, "no. ind") or _buscar_col(df.columns, "ind.")
    c_mun = _buscar_col(df.columns, "municipio", excluir=("cod",))
    c_cob = _buscar_col(df.columns, "cobertura", excluir=("id", "nomencl"))

    cm2 = pd.to_numeric(df[c_cm2], errors="coerce").fillna(0) if c_cm2 else 0
    ind = pd.to_numeric(df[c_ind], errors="coerce").fillna(0) if c_ind else 0
    con_epifita = df[(cm2 > 0) | (ind > 0)] if (c_cm2 or c_ind) else df
    if c_especie:
        con_epifita = con_epifita[con_epifita[c_especie].notna()]

    r = {}
    if c_forofito:
        ids = con_epifita[c_forofito].dropna().astype(str).str.strip()
        r["forofitos"] = str(ids.nunique())
        r["_ids_forofitos"] = sorted(ids.unique().tolist())
    if c_especie:
        esp = con_epifita[[c_especie] + ([c_tipo] if c_tipo else [])].dropna(subset=[c_especie])
        if c_tipo:
            es_nv = esp[c_tipo].astype(str).str.lower().str.contains("no vascular|nv", regex=True)
            r["spp_enov"] = str(esp.loc[es_nv, c_especie].nunique())
            r["spp_ev"] = str(esp.loc[~es_nv, c_especie].nunique())
        r["spp_total"] = str(esp[c_especie].nunique())
    if c_cm2:
        r["cobertura_cm2"] = _entero(float(cm2.sum()))
    if c_mun:
        mun = df[c_mun].dropna().astype(str)
        if not mun.empty:
            r["municipio"] = re.sub(r"\s*\(.*\)$", "", mun.mode().iloc[0]).strip()
    if c_cob:
        r["coberturas"] = ", ".join(df[c_cob].dropna().astype(str).str.strip().unique())
    r["registros"] = str(len(df))
    return r
