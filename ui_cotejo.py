"""
ui_cotejo.py — Vista en tarjetas del cotejo entre documentos.

Cada dato es una tarjeta: el valor grande arriba y, debajo, una ficha pequeña
por cada documento donde aparece (AF, CTL, EP…). La ficha queda verde si su
valor coincide con el de la mayoría y roja si no. Pasando el mouse por la
ficha se ve el documento completo y el valor que trae.
"""

import html
import re

import streamlit as st

# Paleta Unergy (la misma del hub y de Compensación) + verde/rojo de estado
MORADO = "#7B4CC9"
MORADO_OSCURO = "#2D1B4E"
MORADO_CLARO = "#D9CEEF"
MORADO_FONDO = "#F6F2FC"
VERDE, VERDE_FONDO, VERDE_BORDE = "#1E6B3A", "#E3F3E8", "#9FD3B0"
ROJO, ROJO_FONDO, ROJO_BORDE = "#B53D34", "#FBE2E0", "#EBA8A1"
GRIS, GRIS_FONDO = "#5A5A72", "#F1F1F5"

ABREV = {
    "FUN": ("FUN", "Formulario Único Nacional"),
    "Informe AF": ("AF", "Informe de aprovechamiento forestal"),
    "Inventario": ("INV", "Inventario forestal"),
    "Plan Comp.": ("PC", "Plan de compensación"),
    "Aptitud": ("AS", "Aptitud del suelo"),
    "Costos": ("CO", "Costos y presupuesto"),
    "Oficio": ("OF", "Oficio de solicitud"),
    "CTL": ("CTL", "Certificado de tradición y libertad"),
    "CUS": ("CUS", "Certificado de uso del suelo"),
    "Poder Forestal": ("PF", "Poder forestal"),
    "Cédula (IA)": ("CC", "Cédula del propietario"),
    "Epífitas": ("EP", "Informe de caracterización de epífitas"),
    "BD Epífitas": ("BD", "Base de datos de epífitas"),
}

ORDEN_GRUPOS = ["Proyecto y predio", "Propietario", "Aprovechamiento", "Epífitas", "Costos", "General"]

_CSS = f"""
<style>
.fg-resumen {{ display:flex; flex-wrap:wrap; gap:10px; margin:.4rem 0 1.4rem; }}
.fg-pill {{ display:flex; align-items:center; gap:8px; padding:9px 16px; border-radius:999px;
           font-weight:600; font-size:.95rem; }}
.fg-pill b {{ font-size:1.25rem; }}
.fg-pill.ok {{ background:{VERDE_FONDO}; color:{VERDE}; }}
.fg-pill.bad {{ background:{ROJO_FONDO}; color:{ROJO}; }}
.fg-pill.solo {{ background:{GRIS_FONDO}; color:{GRIS}; }}

.fg-grupo {{ font-size:1.05rem; font-weight:700; color:{MORADO_OSCURO}; margin:1.3rem 0 .6rem; }}
.fg-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(255px, 1fr)); gap:14px; }}

.fg-card {{ background:#fff; border:1.5px solid {MORADO_CLARO}; border-radius:14px; padding:14px 16px 13px;
           display:flex; flex-direction:column; gap:8px; min-width:0; }}
.fg-card.ok  {{ border-color:{VERDE_BORDE}; }}
.fg-card.bad {{ border-color:{ROJO_BORDE}; background:#FFFBFA; }}
.fg-card.solo {{ border-style:dashed; }}
.fg-cab {{ display:flex; justify-content:space-between; align-items:center; gap:8px; }}
.fg-dato {{ font-size:.8rem; font-weight:600; color:{GRIS}; }}
.fg-estado {{ font-size:.72rem; font-weight:700; padding:2px 8px; border-radius:999px; white-space:nowrap; }}
.fg-card.ok .fg-estado {{ background:{VERDE_FONDO}; color:{VERDE}; }}
.fg-card.bad .fg-estado {{ background:{ROJO_FONDO}; color:{ROJO}; }}
.fg-card.solo .fg-estado {{ background:{GRIS_FONDO}; color:{GRIS}; }}
.fg-valor {{ font-size:1.18rem; font-weight:700; color:{MORADO_OSCURO}; line-height:1.25;
            overflow-wrap:anywhere; }}
.fg-card.bad .fg-valor {{ color:{ROJO}; }}
.fg-valor.largo {{ font-size:.98rem; }}
.fg-chips {{ display:flex; flex-wrap:wrap; gap:5px; }}
.fg-chip {{ font-size:.72rem; font-weight:700; letter-spacing:.02em; padding:3px 8px; border-radius:6px;
           cursor:help; border:1px solid transparent; }}
.fg-chip.ok  {{ background:{VERDE_FONDO}; color:{VERDE}; border-color:{VERDE_BORDE}; }}
.fg-chip.bad {{ background:{ROJO_FONDO}; color:{ROJO}; border-color:{ROJO_BORDE}; }}
.fg-chip.solo {{ background:{MORADO_FONDO}; color:{MORADO}; border-color:{MORADO_CLARO}; }}
.fg-dif {{ border-top:1px solid #F0E3E1; padding-top:8px; display:flex; flex-direction:column; gap:5px; }}
.fg-dif div {{ display:flex; gap:8px; align-items:baseline; font-size:.84rem; color:#2B2B3A; }}
.fg-dif .fg-chip {{ flex:none; }}

.fg-leyenda {{ font-size:.78rem; color:{GRIS}; margin-top:1rem; line-height:1.7; }}
.fg-leyenda .fg-chip {{ cursor:default; margin-right:2px; }}

.fg-epi {{ display:grid; grid-template-columns:minmax(260px, 1.1fr) 2fr; gap:16px; margin:.3rem 0 .4rem; }}
@media (max-width: 780px) {{ .fg-epi {{ grid-template-columns:1fr; }} }}
.fg-epi-hero {{ background:{MORADO_OSCURO}; color:#fff; border-radius:16px; padding:20px 22px;
               display:flex; flex-direction:column; gap:10px; }}
.fg-epi-hero .n {{ font-size:2.6rem; font-weight:800; line-height:1; }}
.fg-epi-hero .n small {{ font-size:1.1rem; font-weight:600; color:#C5B3F0; }}
.fg-epi-hero .t {{ color:#E4DAF7; font-size:.92rem; }}
.fg-barra {{ height:10px; border-radius:999px; background:rgba(255,255,255,.18); overflow:hidden; }}
.fg-barra span {{ display:block; height:100%; background:#9FE0B5; border-radius:999px; }}
.fg-epi-hero .nota {{ font-size:.8rem; color:#C5B3F0; }}
.fg-epi-hero .alerta {{ background:{ROJO_FONDO}; color:{ROJO}; border-radius:8px; padding:7px 10px;
                        font-size:.82rem; font-weight:600; }}
.fg-mini {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:10px; }}
.fg-mini div {{ background:#fff; border:1.5px solid {MORADO_CLARO}; border-radius:12px; padding:11px 13px; }}
.fg-mini b {{ display:block; font-size:1.15rem; color:{MORADO_OSCURO}; }}
.fg-mini span {{ font-size:.78rem; color:{GRIS}; }}
.fg-mini div.aviso {{ border-color:#F0C36D; background:#FFF8E8; }}
</style>
"""


def _e(s) -> str:
    return html.escape(str(s))


def _limpiar_dato(dato: str) -> str:
    """Quita el emoji del inicio ('🏷️ Matrícula…' -> 'Matrícula…')."""
    return re.sub(r"^[^\wÁÉÍÓÚÑáéíóúñ(]+", "", dato).strip()


def _chip(col: str, valor: str, clase: str) -> str:
    abrev, nombre = ABREV.get(col, (col, col))
    return f'<span class="fg-chip {clase}" title="{_e(nombre)}: {_e(valor)}">{_e(abrev)}</span>'


def _tarjeta(f: dict) -> str:
    fuentes = f.get("fuentes") or {}
    estado = {"✅": "ok", "❌": "bad"}.get(f["✓"], "solo")
    etiqueta = {"ok": "Coincide", "bad": "No coincide", "solo": "1 documento"}[estado]
    valor = f.get("valor", "—")
    clase_valor = "fg-valor largo" if len(str(valor)) > 34 else "fg-valor"

    chips = "".join(
        _chip(col, d["valor"], "solo" if estado == "solo" else ("ok" if d["coincide"] else "bad"))
        for col, d in fuentes.items()
    )
    dif = ""
    if estado == "bad":
        lineas = "".join(
            f'<div>{_chip(col, d["valor"], "ok" if d["coincide"] else "bad")}<span>{_e(d["valor"])}</span></div>'
            for col, d in sorted(fuentes.items(), key=lambda kv: not kv[1]["coincide"])
        )
        dif = f'<div class="fg-dif">{lineas}</div>'
        chips = ""  # en las que no coinciden, la lista de abajo ya muestra cada ficha con su valor
        if valor == "No coinciden":
            valor, clase_valor = "Valores distintos", "fg-valor largo"

    return (
        f'<div class="fg-card {estado}"><div class="fg-cab"><span class="fg-dato">{_e(_limpiar_dato(f["dato"]))}</span>'
        f'<span class="fg-estado">{etiqueta}</span></div>'
        f'<div class="{clase_valor}">{_e(valor)}</div>'
        + (f'<div class="fg-chips">{chips}</div>' if chips else "") + f'{dif}</div>'
    )


def mostrar_resumen(cotejo: list[dict], n_arit_errores: int = 0) -> None:
    filas = [f for f in cotejo if f.get("fuentes")]
    ok = sum(f["✓"] == "✅" for f in filas)
    bad = sum(f["✓"] == "❌" for f in filas)
    solo = sum(f["✓"] == "—" for f in filas)
    pills = (f'<div class="fg-pill ok"><b>{ok}</b> datos coinciden</div>'
             f'<div class="fg-pill bad"><b>{bad}</b> no coinciden</div>'
             f'<div class="fg-pill solo"><b>{solo}</b> aparecen en un solo documento</div>')
    if n_arit_errores:
        pills += f'<div class="fg-pill bad"><b>{n_arit_errores}</b> error(es) aritmético(s)</div>'
    st.markdown(_CSS + f'<div class="fg-resumen">{pills}</div>', unsafe_allow_html=True)


def mostrar_tarjetas(cotejo: list[dict]) -> None:
    filas = [f for f in cotejo if f.get("fuentes")]
    if not filas:
        st.info("No se encontraron datos reconocibles en los documentos.")
        return
    orden_estado = {"❌": 0, "✅": 1, "—": 2}
    grupos = {}
    for f in filas:
        grupos.setdefault(f.get("grupo", "General"), []).append(f)

    partes = []
    for g in sorted(grupos, key=lambda g: ORDEN_GRUPOS.index(g) if g in ORDEN_GRUPOS else 99):
        tarjetas = sorted(grupos[g], key=lambda f: orden_estado.get(f["✓"], 3))
        partes.append(f'<div class="fg-grupo">{_e(g)}</div><div class="fg-grid">'
                      + "".join(_tarjeta(f) for f in tarjetas) + "</div>")

    usados = {col for f in filas for col in f["fuentes"]}
    leyenda = " &nbsp; ".join(
        f'<span class="fg-chip solo">{_e(a)}</span>{_e(n)}' for col, (a, n) in ABREV.items() if col in usados
    )
    st.markdown(_CSS + "".join(partes)
                + f'<div class="fg-leyenda">{leyenda}<br>Pasa el mouse sobre cada ficha para ver el valor que trae ese documento.</div>',
                unsafe_allow_html=True)


def mostrar_epifitas(ep: dict | None) -> None:
    if not ep:
        return
    arboles, foro = ep.get("arboles"), ep.get("forofitos")
    if foro is not None and arboles:
        pct = foro / arboles * 100
        sin = arboles - foro
        hero = (f'<div class="n">{foro} <small>de {arboles} árboles</small></div>'
                f'<div class="t">tienen epífitas (son forófitos) · {pct:.0f}% del inventario</div>'
                f'<div class="fg-barra"><span style="width:{min(pct, 100):.1f}%"></span></div>')
        if sin > 0:
            hero += f'<div class="nota">{sin} árbol(es) del inventario sin epífitas registradas.</div>'
        elif sin < 0:
            hero += (f'<div class="alerta">Hay {-sin} forófito(s) más que árboles en el inventario: '
                     f'revisa los conteos.</div>')
        hero += (f'<div class="nota">Árboles: {_e(ep["fuente_arboles"])} · '
                 f'Forófitos: {_e(ep["fuente_forofitos"])}</div>')
    elif foro is not None:
        hero = (f'<div class="n">{foro} <small>forófitos</small></div>'
                f'<div class="t">con epífitas. Sube el inventario para ver qué porcentaje de los árboles es.</div>')
    else:
        hero = '<div class="t">No se encontró el número de forófitos muestreados en el informe.</div>'

    mini = []

    def m(valor, texto, aviso=False):
        if valor not in (None, "", "None"):
            mini.append(f'<div class="{"aviso" if aviso else ""}"><b>{_e(valor)}</b><span>{_e(texto)}</span></div>')

    m(ep.get("spp_enov"), "especies no vasculares (ENoV)")
    m(ep.get("spp_ev"), "especies vasculares (EV)")
    if ep.get("cobertura_cm2"):
        m(f'{int(float(ep["cobertura_cm2"])):,}'.replace(",", ".") + " cm²", "cobertura total de epífitas")
    rep = ep.get("representatividad_pct")
    if rep is not None:
        m(f"{rep:g}".replace(".", ",") + "%", "representatividad del muestreo" + (" · bajo el 85%" if rep < 85 else ""), aviso=rep < 85)
    if ep.get("area_intervenir_ha") is not None:
        m(f'{ep["area_intervenir_ha"]:g}'.replace(".", ",") + " ha", "área a intervenir")
    m(ep.get("coberturas"), "coberturas evaluadas")

    st.markdown(_CSS + f'<div class="fg-epi"><div class="fg-epi-hero">{hero}</div>'
                f'<div class="fg-mini">{"".join(mini)}</div></div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Documentos detectados y checklist del Oficio
# ---------------------------------------------------------------------------

TIPOS_INFO = {
    "FUN": ("FUN", "Formulario Único Nacional"),
    "INFORME_AF": ("AF", "Informe de aprovechamiento forestal"),
    "INVENTARIO": ("INV", "Inventario forestal"),
    "COMPENSACION": ("PC", "Plan de compensación"),
    "APTITUD": ("AS", "Aptitud del suelo"),
    "COSTOS": ("CO", "Costos y presupuesto"),
    "OFICIO": ("OF", "Oficio de solicitud"),
    "CTL": ("CTL", "Certificado de tradición y libertad"),
    "CUS": ("CUS", "Certificado de uso del suelo"),
    "PODER": ("PF", "Poder forestal"),
    "CEDULA": ("CC", "Cédula del propietario"),
    "CEDULA_APODERADO": ("CA", "Cédula del apoderado"),
    "EPIFITAS": ("EP", "Caracterización de epífitas"),
    "BD_EPIFITAS": ("BD", "Base de datos de epífitas"),
    "DESCONOCIDO": ("—", "Otro documento (no se coteja)"),
}

ABREV["Cédula apoderado (IA)"] = ("CA", "Cédula del apoderado")

_CSS_DOCS = f"""
<style>
.fg-doc-cab {{ display:flex; align-items:center; gap:9px; margin-bottom:4px; }}
.fg-doc-cab b {{ color:{MORADO_OSCURO}; font-size:.95rem; line-height:1.2; }}
.fg-doc-abrev {{ flex:none; min-width:40px; text-align:center; font-size:.75rem; font-weight:800;
                padding:5px 7px; border-radius:8px; background:{MORADO}; color:#fff; }}
.fg-doc-abrev.otro {{ background:{GRIS_FONDO}; color:{GRIS}; }}
.fg-doc-arch {{ font-size:.78rem; color:{GRIS}; overflow-wrap:anywhere; margin-bottom:7px; }}
.fg-doc-badges {{ display:flex; flex-wrap:wrap; gap:5px; min-height:24px; }}
.fg-b {{ font-size:.72rem; font-weight:600; padding:3px 8px; border-radius:999px; }}
.fg-b.ok {{ background:{VERDE_FONDO}; color:{VERDE}; }}
.fg-b.warn {{ background:#FFF3D6; color:#8A5A00; }}
.fg-b.bad {{ background:{ROJO_FONDO}; color:{ROJO}; }}
.fg-b.gris {{ background:{GRIS_FONDO}; color:{GRIS}; }}

.fg-check-resumen {{ display:flex; align-items:center; gap:14px; margin:.2rem 0 .9rem; }}
.fg-check-resumen .n {{ font-size:1.6rem; font-weight:800; color:{MORADO_OSCURO}; }}
.fg-check-resumen .t {{ color:{GRIS}; font-size:.9rem; }}
.fg-check-barra {{ flex:1; max-width:320px; height:9px; border-radius:999px; background:{GRIS_FONDO}; overflow:hidden; }}
.fg-check-barra span {{ display:block; height:100%; background:{VERDE}; }}
.fg-check-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(290px, 1fr)); gap:9px; }}
.fg-check {{ display:flex; gap:10px; align-items:flex-start; padding:10px 12px; border-radius:11px;
            border:1.5px solid {VERDE_BORDE}; background:#fff; }}
.fg-check.falta {{ border-color:{ROJO_BORDE}; background:#FFFBFA; }}
.fg-check .ic {{ flex:none; width:22px; height:22px; border-radius:50%; display:grid; place-items:center;
                font-size:.75rem; font-weight:800; background:{VERDE_FONDO}; color:{VERDE}; }}
.fg-check.falta .ic {{ background:{ROJO_FONDO}; color:{ROJO}; }}
.fg-check .it {{ font-size:.86rem; font-weight:600; color:#2B2B3A; line-height:1.3; }}
.fg-check .ev {{ font-size:.74rem; color:{GRIS}; margin-top:2px; overflow-wrap:anywhere; }}
.fg-check.falta .ev {{ color:{ROJO}; }}
</style>
"""


def css_documentos() -> None:
    st.markdown(_CSS + _CSS_DOCS, unsafe_allow_html=True)


def etiqueta_tipo(tipo: str) -> str:
    abrev, nombre = TIPOS_INFO.get(tipo, (tipo, tipo))
    return f"{abrev} · {nombre}" if abrev != "—" else nombre


def cabecera_documento(tipo: str, nombre_archivo: str, vigencia: dict, n_resaltado: int) -> str:
    abrev, nombre = TIPOS_INFO.get(tipo, ("?", tipo))
    clase = "fg-doc-abrev otro" if tipo == "DESCONOCIDO" else "fg-doc-abrev"
    badges = []
    est = (vigencia or {}).get("estado", "sin_fecha")
    fecha = (vigencia or {}).get("fecha")
    if fecha:
        f = fecha.strftime("%d/%m/%Y")
        badges.append({
            "vigente": f'<span class="fg-b ok">Vigente · {f}</span>',
            "revisar": f'<span class="fg-b warn">Revisar antigüedad · {f}</span>',
            "desactualizado": f'<span class="fg-b bad">Desactualizado · {f}</span>',
            "fecha_futura": f'<span class="fg-b warn">Fecha futura · {f}</span>',
        }.get(est, f'<span class="fg-b gris">{f}</span>'))
    else:
        badges.append('<span class="fg-b gris">Sin fecha</span>')
    if n_resaltado:
        badges.append(f'<span class="fg-b warn">🟨 {n_resaltado} resaltado(s)</span>')
    return (f'<div class="fg-doc-cab"><span class="{clase}">{_e(abrev)}</span><b>{_e(nombre)}</b></div>'
            f'<div class="fg-doc-arch">📎 {_e(nombre_archivo)}</div>'
            f'<div class="fg-doc-badges">{"".join(badges)}</div>')


def mostrar_checklist(checklist: list[dict]) -> None:
    total = len(checklist)
    ok = sum(c["encontrado"] for c in checklist)
    pct = ok / total * 100 if total else 0
    items = []
    for c in sorted(checklist, key=lambda c: c["encontrado"]):  # faltantes primero
        if c["encontrado"]:
            ev = re.sub(r"\s*\([A-Z_]+\)$", "", str(c.get("evidencia") or ""))
            items.append(f'<div class="fg-check"><span class="ic">✓</span><div>'
                         f'<div class="it">{_e(c["item"])}</div><div class="ev">{_e(ev)}</div></div></div>')
        else:
            items.append(f'<div class="fg-check falta"><span class="ic">✕</span><div>'
                         f'<div class="it">{_e(c["item"])}</div><div class="ev">No está entre los documentos subidos</div></div></div>')
    st.markdown(
        _CSS + _CSS_DOCS
        + f'<div class="fg-check-resumen"><span class="n">{ok} de {total}</span>'
        f'<span class="t">documentos que el Oficio dice anexar</span>'
        f'<span class="fg-check-barra"><span style="width:{pct:.0f}%"></span></span></div>'
        + f'<div class="fg-check-grid">{"".join(items)}</div>',
        unsafe_allow_html=True,
    )
