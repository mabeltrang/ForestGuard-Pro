import pandas as pd
import streamlit as st

from resolucion_checker import (
    TOLERANCIA_DIAS_DEFECTO, TRAMOS_COMISION_DEFECTO, Severidad,
    contar_dias, extraer_resolucion, fechas_clave, revisar, tramo_comision,
)

ICONOS = {Severidad.ERROR: "❌", Severidad.ALERTA: "⚠️", Severidad.INFO: "ℹ️"}
EMPRESA = "UNERGY"


def _pesos(valor: int) -> str:
    return f"${valor:,.0f}".replace(",", ".")


def _texto(valor: object) -> str:
    return str(valor) if valor not in (None, "", []) else "—"


def _seccion_plazos(datos: dict, nombre: str) -> None:
    res = datos.get("resolucion") or {}
    rad = datos.get("radicado") or {}
    st.markdown("**⏱️ Tiempo de respuesta y comisión del tramitador**")
    f_rad, f_res = fechas_clave(datos)
    c1, c2 = st.columns(2)
    f_rad = c1.date_input(f"Fecha de radicado ({_texto(rad.get('numero'))})", value=f_rad,
                          format="DD/MM/YYYY", key=f"res_rad_{nombre}")
    f_res = c2.date_input("Fecha de la resolución", value=f_res,
                          format="DD/MM/YYYY", key=f"res_fecha_{nombre}")
    if not (f_rad and f_res):
        st.warning("Falta alguna fecha; complétala arriba para calcular los días.")
        return
    calendario, habiles, festivos = contar_dias(f_rad, f_res)
    tramo = tramo_comision(calendario, TRAMOS_COMISION_DEFECTO, TOLERANCIA_DIAS_DEFECTO)
    m1, m2, m3 = st.columns(3)
    m1.metric("Días calendario", calendario)
    m2.metric("Días hábiles", habiles)
    m3.metric("Comisión", _pesos(tramo.valor) if tramo else "Fuera de tramos")
    if tramo and calendario > tramo.dias_max:
        st.info(f"Se pasó {calendario - tramo.dias_max} día(s) del límite de {tramo.dias_max}, "
                f"pero entra en la tolerancia de {TOLERANCIA_DIAS_DEFECTO} días y se paga {_pesos(tramo.valor)}.")
    if festivos:
        st.caption("Festivos en el periodo: " + ", ".join(d.strftime("%d/%m") for d in festivos))
    hitos = [("Radicado", rad.get("fecha")),
             ("Auto de inicio", (datos.get("auto_inicio") or {}).get("fecha")),
             ("Concepto técnico", (datos.get("concepto_tecnico") or {}).get("fecha")),
             ("Resolución", res.get("fecha"))]
    with st.expander("Ver hitos del trámite"):
        st.table(pd.DataFrame(hitos, columns=["Hito", "Fecha"]))


def _seccion_hallazgos(datos: dict) -> None:
    hallazgos = revisar(datos, EMPRESA)
    n_err = sum(h.severidad == Severidad.ERROR for h in hallazgos)
    n_ale = sum(h.severidad == Severidad.ALERTA for h in hallazgos)
    st.markdown("**🔎 Hallazgos**")
    if n_err or n_ale:
        st.error(f"{n_err} error(es) y {n_ale} alerta(s) en la resolución.")
    else:
        st.success("No se detectaron errores en la resolución.")
    for sev in (Severidad.ERROR, Severidad.ALERTA, Severidad.INFO):
        for h in (h for h in hallazgos if h.severidad == sev):
            st.markdown(f"{ICONOS[sev]} **{h.titulo}** — {h.detalle}")


def _seccion_titular_predio(datos: dict) -> None:
    tit = datos.get("titular_autorizado") or {}
    sol = datos.get("solicitante") or {}
    pre = datos.get("predio") or {}
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**👤 Titular**")
        st.markdown(f"Autorizado: {_texto(tit.get('nombre'))} (CC {_texto(tit.get('cedula'))}) "
                    f"— {_texto(tit.get('calidad'))}")
        st.markdown(f"Solicitante: {_texto(sol.get('empresa'))} · NIT {_texto(sol.get('nit'))} "
                    f"· {_texto(sol.get('calidad'))}")
        st.markdown(f"Notificación: {_texto(datos.get('correo_notificacion'))}")
    with col_b:
        st.markdown("**📍 Predio**")
        st.markdown(f"{_texto(pre.get('nombre'))} · Vda. {_texto(pre.get('vereda'))}, "
                    f"{_texto(pre.get('municipio'))} ({_texto(pre.get('departamento'))})")
        st.markdown(f"Matrícula {_texto(pre.get('matricula'))} · Predio {_texto(pre.get('area_predio_ha'))} ha "
                    f"· Intervención {_texto(pre.get('area_intervencion_ha'))} ha")


def _seccion_aprovechamiento(datos: dict) -> None:
    st.markdown("**🌳 Aprovechamiento autorizado**")
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
    st.markdown("**🌱 Compensación**")
    grupos = [g for g in comp.get("grupos") or [] if isinstance(g, dict)]
    if grupos:
        st.dataframe(pd.DataFrame(grupos).rename(columns={
            "descripcion": "Grupo", "relacion": "Relación 1:n", "arboles_talados": "Talados",
            "arboles_a_reponer": "A reponer"}), hide_index=True, width="stretch")
    st.markdown(f"Total a sembrar: **{_texto(comp.get('total_arboles_a_reponer'))} árboles** · "
                f"Dónde: {_texto(comp.get('lugar'))}")
    st.markdown(f"Mantenimiento: {_texto(comp.get('mantenimiento'))} · Informe: {_texto(comp.get('informe'))}")


def _seccion_obligaciones(datos: dict) -> None:
    st.markdown("**📋 Obligaciones, plazos y pagos**")
    st.markdown(f"Plazo de ejecución: {_texto(datos.get('plazo_ejecucion'))}")
    st.markdown(f"Recurso: {_texto(datos.get('recurso'))}")
    st.markdown(f"Tarifa de seguimiento: {'Sí' if datos.get('cobra_tarifa_seguimiento') else 'No'} · "
                f"Publicación: {'Sí' if datos.get('ordena_publicacion') else 'No'}")
    for o in datos.get("obligaciones") or []:
        st.markdown(f"- {o}")
    consignaciones = [c for c in datos.get("consignaciones") or [] if isinstance(c, dict)]
    if consignaciones:
        st.markdown("Consignaciones citadas:")
        st.dataframe(pd.DataFrame(consignaciones), hide_index=True, width="stretch")


def mostrar_revision_resolucion(file_bytes: bytes, nombre: str) -> None:
    cache = st.session_state.setdefault("_fg_resoluciones", {})
    clave = f"{nombre}|{len(file_bytes)}"
    if clave not in cache:
        with st.spinner(f"Leyendo la resolución {nombre}… (puede tardar un minuto)"):
            cache[clave] = extraer_resolucion(file_bytes)
    datos = cache[clave]

    st.subheader(f"📑 Revisión de resolución — {nombre}")
    if not datos:
        st.error("No se pudo leer la resolución. Verifica la ANTHROPIC_API_KEY y que el PDF no esté protegido.")
        if st.button("Reintentar", key=f"res_reintentar_{nombre}"):
            cache.pop(clave, None)
            st.rerun()
        return

    res = datos.get("resolucion") or {}
    st.caption(f"{_texto(res.get('numero'))} · {_texto(res.get('autoridad'))} · "
               f"Proyecto: {_texto(datos.get('proyecto'))} · Expediente: {_texto(datos.get('expediente'))}")
    _seccion_plazos(datos, nombre)
    _seccion_hallazgos(datos)
    _seccion_titular_predio(datos)
    _seccion_aprovechamiento(datos)
    _seccion_obligaciones(datos)
    with st.expander("🔧 Datos extraídos de la resolución (debug)"):
        st.json(datos)
