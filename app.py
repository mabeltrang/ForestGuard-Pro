import streamlit as st
import os
import tempfile
from extractor import extract_text_from_file
from analyzer import clasificar_documento, extraer_fun, extraer_informe_af, \
    extraer_compensacion, extraer_aptitud_suelo, extraer_costos, extraer_oficio, analizar_paquete

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="ForestGuard Pro - Validador",
    page_icon="🌲",
    layout="wide"
)

EXTRACTORES = {
    "FUN": extraer_fun,
    "INFORME_AF": extraer_informe_af,
    "COMPENSACION": extraer_compensacion,
    "APTITUD": extraer_aptitud_suelo,
    "COSTOS": extraer_costos,
    "OFICIO": extraer_oficio,
}

LABELS = {
    "FUN": "📋 FUN",
    "INFORME_AF": "🌳 Informe AF",
    "COMPENSACION": "🌱 Plan Compensación",
    "APTITUD": "🗺️ Aptitud Suelo",
    "COSTOS": "💰 Costos",
    "OFICIO": "📄 Oficio",
    "DESCONOCIDO": "❓ Desconocido",
}

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("🌲 ForestGuard Pro — Validador de Paquetes Forestales")
st.markdown("Detecta inconsistencias entre documentos del paquete forestal sin necesidad de IA externa.")

with st.sidebar:
    st.header("ℹ️ Cómo usar")
    st.markdown("""
    1. Sube todos los documentos del paquete
    2. Verifica que cada uno fue clasificado correctamente
    3. Haz clic en **Validar Paquete**
    4. Revisa la tabla de cotejo y las inconsistencias

    **Documentos soportados:**
    - Formato Único Nacional (FUN)
    - Informe de Aprovechamiento Forestal
    - Plan de Compensación *(separado o dentro del AF)*
    - Informe de Aptitud del Suelo
    - Costos y Presupuesto
    - Oficio de Solicitud

    *(PDF, DOCX, XLSX)*
    """)
    st.markdown("---")
    st.caption("Validación 100% local — sin API keys requeridas.")

# Carga de archivos
uploaded_files = st.file_uploader(
    "Sube los documentos del paquete forestal",
    accept_multiple_files=True,
    type=["pdf", "docx", "doc", "xlsx", "xls"]
)

if not uploaded_files:
    st.info("👆 Sube los documentos para comenzar.")
    st.stop()

# ---------------------------------------------------------------------------
# EXTRACCIÓN Y CLASIFICACIÓN
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("1️⃣ Documentos detectados")

documentos_texto = {}
documentos_tipo = {}
documentos_datos = {}

for file in uploaded_files:
    suffix = os.path.splitext(file.name)[1]
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file.getbuffer())
            tmp_path = tmp.name

        texto = extract_text_from_file(tmp_path)
        documentos_texto[file.name] = texto
        tipo = clasificar_documento(file.name, texto)
        documentos_tipo[file.name] = tipo

    except Exception as e:
        st.error(f"Error procesando {file.name}: {e}")
        documentos_tipo[file.name] = "DESCONOCIDO"
        documentos_texto[file.name] = ""
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

# Clasificación con corrección manual
tipo_opciones = ["FUN", "INFORME_AF", "COMPENSACION", "APTITUD", "COSTOS", "OFICIO", "DESCONOCIDO"]
asignaciones = {}

cols = st.columns([3, 2])
with cols[0]:
    st.markdown("**Archivo**")
with cols[1]:
    st.markdown("**Tipo detectado** (puedes corregir)")

for nombre, tipo_auto in documentos_tipo.items():
    c1, c2 = st.columns([3, 2])
    with c1:
        st.write(f"📎 {nombre}")
    with c2:
        idx = tipo_opciones.index(tipo_auto) if tipo_auto in tipo_opciones else 5
        tipo_final = st.selectbox(
            label=f"Tipo para {nombre}",
            options=tipo_opciones,
            index=idx,
            key=f"tipo_{nombre}",
            label_visibility="collapsed"
        )
        asignaciones[nombre] = tipo_final

for nombre, tipo in asignaciones.items():
    if tipo in EXTRACTORES and documentos_texto.get(nombre):
        datos = EXTRACTORES[tipo](documentos_texto[nombre])
        documentos_datos[tipo] = datos

# ---------------------------------------------------------------------------
# VALIDACIÓN
# ---------------------------------------------------------------------------
st.markdown("---")
if st.button("🔍 Validar Paquete", type="primary"):

    if len(documentos_datos) < 2:
        st.warning("Sube al menos 2 documentos clasificados para comparar.")
        st.stop()

    resultado = analizar_paquete(documentos_datos)
    cotejo = resultado["cotejo"]
    incoherencias = resultado["incoherencias"]
    aritmetica = resultado["aritmetica"]

    n_errores = sum(1 for f in cotejo if f["consistente"] == "❌")
    n_arit_errores = sum(1 for a in aritmetica if a["ok"] == "❌")

    if n_errores == 0 and n_arit_errores == 0:
        st.success("✅ No se detectaron inconsistencias. El paquete parece consistente.")
    else:
        st.error(f"❌ Se detectaron **{n_errores} inconsistencia(s)** entre documentos y **{n_arit_errores} error(es) aritmético(s)**.")

    st.markdown("---")
    st.subheader("2️⃣ Tabla de cotejo")

    import pandas as pd
    df = pd.DataFrame(cotejo)
    df = df.rename(columns={
        "dato": "Dato",
        "consistente": "✓",
        "Informe AF": "Informe AF",
        "Plan Comp.": "Plan Comp.",
    })

    def colorear(val):
        if val == "❌":
            return "background-color: #ffd6d6; color: #c0392b; font-weight: bold"
        if val == "✅":
            return "background-color: #d6f5d6; color: #1e8449"
        return ""

    try:
        styled = df.style.map(colorear, subset=["✓"])
    except AttributeError:
        styled = df.style.applymap(colorear, subset=["✓"])

    st.dataframe(styled, width="stretch", hide_index=True)

    if incoherencias:
        st.markdown("---")
        st.subheader("3️⃣ Detalle de inconsistencias")
        for i, inc in enumerate(incoherencias, 1):
            with st.expander(f"❌ INCOHERENCIA #{i} — {inc['dato']}", expanded=True):
                for doc, val in inc["valores"].items():
                    st.markdown(f"- **{doc}:** `{val}`")
                st.caption("Corrige el valor en el documento que tenga el error antes de radicar.")

    if aritmetica:
        st.markdown("---")
        st.subheader("4️⃣ Verificación aritmética")
        for a in aritmetica:
            st.markdown(
                f"{a['ok']} **{a['verificacion']}** — "
                f"{a['operacion']} → reportado: `{a['reportado']}`"
            )

    with st.expander("🔧 Ver valores extraídos por documento (debug)", expanded=False):
        for tipo, datos in resultado["datos_crudos"].items():
            st.markdown(f"**{LABELS.get(tipo, tipo)}**")
            for k, v in datos.items():
                if v:
                    st.markdown(f"- `{k}`: {v}")
