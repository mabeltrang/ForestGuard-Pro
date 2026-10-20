import pandas as pd
import streamlit as st

from resolucion_checker import (
    TOLERANCIA_DIAS_DEFECTO, TRAMOS_COMISION_DEFECTO, ModoDias, Severidad, TramoComision,
    contar_dias, extraer_resolucion, fechas_clave, revisar, tramo_comision,
)

st.set_page_config(page_title="ForestGuard Pro - Resoluciones", page_icon="📑", layout="wide")

ICONOS = {Severidad.ERROR: "❌", Severidad.ALERTA: "⚠️", Severidad.INFO: "ℹ️"}


def _pesos(valor: int) -> str:
    return f"${valor:,.0f}".replace(",", ".")


def _texto(valor: object) -> str:
    return str(valor) if valor not in (None, "", []) else "—"


with st.sidebar:
    st.header("⚙️ Comisión del tramitador")
    modo = st.radio("Contar días", [m.value for m in ModoDias], index=0, horizontal=True)
    tramos = []
    for i, t in enumerate(TRAMOS_COMISION_DEFECTO):
        c1, c2, c3 = st.columns(3)
        dmin = c1.number_input("Desde", value=t.dias_min, step=1, key=f"min{i}")
        dmax = c2.number_input("Hasta", value=t.dias_max, step=1, key=f"max{i}")
        valor = c3.number_input("Valor", value=t.valor, step=10_000, key=f"val{i}")
        tramos.append(TramoComision(int(dmin), int(dmax), int(valor)))
    tolerancia = st.number_input("Días de tolerancia", min_value=0, value=TOLERANCIA_DIAS_DEFECTO, step=1,
                                 help="Días extra sobre el límite de cada tramo que se siguen pagando como ese tramo.")
    empresa = st.text_input("Empresa solicitante", value="UNERGY")
    st.caption("La resolución se lee con IA (visión de Anthropic).")

st.title("📑 Revisión de resolución")
st.markdown("Sube la resolución de la autoridad ambiental y revisa plazos, comisión, "
            "titular, compensación y errores del acto.")

archivo = st.file_uploader("Resolución (PDF)", type=["pdf"])
if not archivo:
    st.info("👆 Sube una resolución para revisarla.")
    st.stop()

cache = st.session_state.setdefault("_fg_resoluciones", {})
clave = f"{archivo.name}|{archivo.size}"
if clave not in cache:
    with st.spinner("Leyendo la resolución… (puede tardar un minuto)"):
        cache[clave] = extraer_resolucion(archivo.getvalue())
datos = cache[clave]

if not datos:
    st.error("No se pudo leer la resolución. Verifica la ANTHROPIC_API_KEY y que el PDF no esté protegido.")
    if st.button("Reintentar"):
        cache.pop(clave, None)
        st.rerun()
    st.stop()

res = datos.get("resolucion") or {}
rad = datos.get("radicado") or {}
st.subheader(f"{_texto(res.get('numero'))} · {_texto(res.get('autoridad'))}")
st.caption(f"Proyecto: {_texto(datos.get('proyecto'))} · Expediente: {_texto(datos.get('expediente'))} "
           f"· Sentido: {_texto(res.get('sentido'))}")

# --- Plazos y comisión -------------------------------------------------------
st.markdown("---")
st.subheader("⏱️ Tiempo de respuesta y comisión")
f_rad, f_res = fechas_clave(datos)
c1, c2 = st.columns(2)
f_rad = c1.date_input(f"Fecha de radicado ({_texto(rad.get('numero'))})", value=f_rad, format="DD/MM/YYYY")
f_res = c2.date_input("Fecha de la resolución", value=f_res, format="DD/MM/YYYY")

if f_rad and f_res:
    calendario, habiles, festivos = contar_dias(f_rad, f_res)
    dias = calendario if modo == ModoDias.CALENDARIO.value else habiles
    tramo = tramo_comision(dias, tuple(tramos), int(tolerancia))
    m1, m2, m3 = st.columns(3)
    m1.metric("Días calendario", calendario)
    m2.metric("Días hábiles", habiles)
    m3.metric(f"Comisión ({modo})", _pesos(tramo.valor) if tramo else "Fuera de tramos",
              help=f"Tramo {tramo.dias_min}-{tramo.dias_max} días" if tramo else None)
    if tramo and dias > tramo.dias_max:
        st.info(f"Se pasó {dias - tramo.dias_max} día(s) del límite de {tramo.dias_max}, "
                f"pero entra en la tolerancia de {int(tolerancia)} y se paga {_pesos(tramo.valor)}.")
    if festivos:
        st.caption("Festivos descontados: " + ", ".join(d.strftime("%d/%m") for d in festivos))
    hitos = [("Radicado", rad.get("fecha")),
             ("Auto de inicio", (datos.get("auto_inicio") or {}).get("fecha")),
             ("Concepto técnico", (datos.get("concepto_tecnico") or {}).get("fecha")),
             ("Resolución", res.get("fecha"))]
    with st.expander("Ver hitos del trámite"):
        st.table(pd.DataFrame(hitos, columns=["Hito", "Fecha"]))
else:
    st.warning("Falta alguna fecha; complétala arriba para calcular los días.")

# --- Hallazgos ---------------------------------------------------------------
hallazgos = revisar(datos, empresa)
n_err = sum(h.severidad == Severidad.ERROR for h in hallazgos)
n_ale = sum(h.severidad == Severidad.ALERTA for h in hallazgos)
st.markdown("---")
st.subheader("🔎 Hallazgos")
if n_err or n_ale:
    st.error(f"{n_err} error(es) y {n_ale} alerta(s) en la resolución.")
else:
    st.success("No se detectaron errores en la resolución.")
for sev in (Severidad.ERROR, Severidad.ALERTA, Severidad.INFO):
    for h in (h for h in hallazgos if h.severidad == sev):
        st.markdown(f"{ICONOS[sev]} **{h.titulo}** — {h.detalle}")

# --- Titular y predio --------------------------------------------------------
st.markdown("---")
col_a, col_b = st.columns(2)
tit = datos.get("titular_autorizado") or {}
sol = datos.get("solicitante") or {}
pre = datos.get("predio") or {}
with col_a:
    st.subheader("👤 Titular")
    st.markdown(f"**Autorizado:** {_texto(tit.get('nombre'))} (CC {_texto(tit.get('cedula'))}) "
                f"— {_texto(tit.get('calidad'))}")
    st.markdown(f"**Solicitante:** {_texto(sol.get('empresa'))} · NIT {_texto(sol.get('nit'))} "
                f"· {_texto(sol.get('calidad'))}")
    st.markdown(f"**Notificación:** {_texto(datos.get('correo_notificacion'))}")
with col_b:
    st.subheader("📍 Predio")
    st.markdown(f"**{_texto(pre.get('nombre'))}** · Vda. {_texto(pre.get('vereda'))}, "
                f"{_texto(pre.get('municipio'))} ({_texto(pre.get('departamento'))})")
    st.markdown(f"Matrícula {_texto(pre.get('matricula'))} · Predio {_texto(pre.get('area_predio_ha'))} ha "
                f"· Intervención {_texto(pre.get('area_intervencion_ha'))} ha")

# --- Aprovechamiento y compensación -----------------------------------------
st.markdown("---")
st.subheader("🌳 Aprovechamiento autorizado")
especies = [e for e in datos.get("especies") or [] if isinstance(e, dict)]
if especies:
    st.dataframe(pd.DataFrame(especies).rename(columns={
        "nombre_comun": "Nombre común", "nombre_cientifico": "Nombre científico",
        "arboles": "Árboles", "volumen_m3": "Volumen (m³)", "categoria_amenaza": "Amenaza"}),
        hide_index=True, width="stretch")
st.caption(f"Total: {_texto(datos.get('total_arboles'))} árboles · {_texto(datos.get('volumen_total_m3'))} m³ "
           f"· Muestreo de verificación: {_texto(datos.get('intensidad_muestreo_pct'))} % "
           f"· Objeto: {_texto(datos.get('objeto_aprovechamiento'))}")

comp = datos.get("compensacion") or {}
st.subheader("🌱 Compensación")
grupos = [g for g in comp.get("grupos") or [] if isinstance(g, dict)]
if grupos:
    st.dataframe(pd.DataFrame(grupos).rename(columns={
        "descripcion": "Grupo", "relacion": "Relación 1:n", "arboles_talados": "Talados",
        "arboles_a_reponer": "A reponer"}), hide_index=True, width="stretch")
st.markdown(f"**Total a sembrar:** {_texto(comp.get('total_arboles_a_reponer'))} árboles · "
            f"**Dónde:** {_texto(comp.get('lugar'))}")
st.markdown(f"**Mantenimiento:** {_texto(comp.get('mantenimiento'))} · **Informe:** {_texto(comp.get('informe'))}")

# --- Obligaciones ------------------------------------------------------------
st.markdown("---")
st.subheader("📋 Obligaciones, plazos y pagos")
st.markdown(f"**Plazo de ejecución:** {_texto(datos.get('plazo_ejecucion'))}")
st.markdown(f"**Recurso:** {_texto(datos.get('recurso'))}")
st.markdown(f"**Tarifa de seguimiento:** {'Sí' if datos.get('cobra_tarifa_seguimiento') else 'No'} · "
            f"**Publicación:** {'Sí' if datos.get('ordena_publicacion') else 'No'}")
for o in datos.get("obligaciones") or []:
    st.markdown(f"- {o}")
consignaciones = [c for c in datos.get("consignaciones") or [] if isinstance(c, dict)]
if consignaciones:
    st.markdown("**Consignaciones citadas:**")
    st.dataframe(pd.DataFrame(consignaciones), hide_index=True, width="stretch")

with st.expander("🔧 Datos extraídos (debug)"):
    st.json(datos)
