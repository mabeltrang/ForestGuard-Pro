import streamlit as st
import os
import tempfile
from extractor import extract_text_from_file
from analyzer import clasificar_documento, extraer_fun, extraer_informe_af, \
    extraer_compensacion, extraer_aptitud_suelo, extraer_costos, extraer_oficio, \
    extraer_inventario, analizar_paquete

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
    "INVENTARIO": extraer_inventario,
    "COMPENSACION": extraer_compensacion,
    "APTITUD": extraer_aptitud_suelo,
    "COSTOS": extraer_costos,
    "OFICIO": extraer_oficio,
}

LABELS = {
    "FUN": "📋 FUN",
    "INFORME_AF": "🌳 Informe AF",
    "INVENTARIO": "🌲 Inventario Forestal",
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
    - Inventario Forestal (Excel o PDF)
    - Plan de Compensación *(separado o dentro del AF)*
    - Informe de Aptitud del Suelo
    - Costos y Presupuesto
    - Oficio de Solicitud

    *(PDF, DOCX, XLSX)*
    """)
    st.markdown("---")
    st.caption("Validación 100% local — sin API keys ni servicios externos.")

# Carga de archivos
uploaded_files = st.file_uploader(
    "Sube los documentos del paquete forestal",
    accept_multiple_files=True,
    type=["pdf", "docx", "doc", "xlsx", "xls"]
)

if not uploaded_files:
    st.info("👆 Sube los documentos del paquete para validar.")

# ---------------------------------------------------------------------------
if uploaded_files:
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
            raw_bytes = file.getbuffer()
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(raw_bytes)
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
    tipo_opciones = ["FUN", "INFORME_AF", "INVENTARIO", "COMPENSACION", "APTITUD", "COSTOS", "OFICIO", "DESCONOCIDO"]
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
            idx = tipo_opciones.index(tipo_auto) if tipo_auto in tipo_opciones else tipo_opciones.index("DESCONOCIDO")
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

        if not documentos_datos:
            st.warning("No se pudo extraer información de los documentos cargados.")
        else:
            resultado = analizar_paquete(documentos_datos)
            cotejo = resultado["cotejo"]
            incoherencias = resultado["incoherencias"]
            aritmetica = resultado["aritmetica"]

            n_errores = sum(1 for f in cotejo if f["✓"] == "❌")
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
            })

            # Quitar columnas de docs que no se cargaron (todas vacías o "—")
            doc_cols = ["FUN", "Informe AF", "Inventario", "Plan Comp.", "Aptitud", "Costos", "Oficio"]
            cols_con_datos = [
                c for c in doc_cols
                if c in df.columns and df[c].notna().any() and (df[c] != "—").any()
            ]
            cols_mostrar = ["Dato"] + cols_con_datos + ["✓"]
            df = df[[c for c in cols_mostrar if c in df.columns]]

            # Quitar filas donde ningún doc tiene datos
            if cols_con_datos:
                df = df[df[cols_con_datos].apply(
                    lambda row: any(v and v != "—" for v in row), axis=1
                )]

            # ---- Tabla HTML con colores de marca Unergy, ancho completo, sin scroll interno ----
            VERDE_OSCURO = "#004d24"
            VERDE = "#006B33"
            VERDE_CLARO = "#4CAF50"
            VERDE_FILA = "#eaf5ee"   # fondo muy suave para filas alternas
            VERDE_OK_BG = "#e3f3e8"
            VERDE_OK_TXT = "#1e6b3a"
            ROJO_BG = "#fbe2e0"
            ROJO_TXT = "#b53d34"

            def _celda_check(v):
                if v == "✅":
                    return f'<td style="padding:9px 10px;background:{VERDE_OK_BG};color:{VERDE_OK_TXT};text-align:center;font-weight:700;">✓</td>'
                if v == "❌":
                    return f'<td style="padding:9px 10px;background:{ROJO_BG};color:{ROJO_TXT};text-align:center;font-weight:700;">✗</td>'
                return '<td style="padding:9px 10px;text-align:center;color:#aab3ac;">—</td>'

            if df.empty:
                st.info("No se encontraron campos reconocibles en el documento.")
            else:
                cols_datos = [c for c in df.columns if c not in ("Dato", "✓")]
                header_html = (
                    f'<th style="background:{VERDE_OSCURO};color:white;padding:10px 14px;'
                    f'text-align:left;font-weight:700;">Dato</th>'
                )
                for c in cols_datos:
                    header_html += (
                        f'<th style="background:{VERDE};color:white;padding:10px 10px;'
                        f'text-align:left;font-weight:600;">{c}</th>'
                    )
                header_html += (
                    f'<th style="background:{VERDE_OSCURO};color:white;padding:10px 10px;'
                    f'text-align:center;font-weight:700;">✓</th>'
                )

                filas_html = ""
                for i, (_, row) in enumerate(df.iterrows()):
                    bg = VERDE_FILA if i % 2 == 1 else "#ffffff"
                    filas_html += f'<tr style="background:{bg};">'
                    filas_html += (
                        f'<td style="padding:9px 14px;font-weight:600;color:{VERDE_OSCURO};'
                        f'word-wrap:break-word;">{row["Dato"]}</td>'
                    )
                    for c in cols_datos:
                        val = row[c]
                        if val in ("—", None, ""):
                            filas_html += '<td style="padding:9px 10px;text-align:center;color:#aab3ac;">—</td>'
                        else:
                            filas_html += f'<td style="padding:9px 10px;color:#2b2b2b;word-wrap:break-word;">{val}</td>'
                    filas_html += _celda_check(row["✓"])
                    filas_html += "</tr>"

                tabla_html = f"""
                <div style="width:100%;border-radius:10px;
                            box-shadow:0 1px 4px rgba(0,0,0,0.12);margin-bottom:1rem;">
                <table style="width:100%;border-collapse:collapse;font-size:13.5px;
                              font-family:inherit;table-layout:fixed;">
                    <colgroup>
                        <col style="width:18%;">
                        {"".join(f'<col style="width:{round(64/len(cols_datos),1)}%;">' for _ in cols_datos)}
                        <col style="width:6%;">
                    </colgroup>
                    <thead><tr>{header_html}</tr></thead>
                    <tbody>{filas_html}</tbody>
                </table>
                </div>
                """
                st.markdown(tabla_html, unsafe_allow_html=True)

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
