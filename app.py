import streamlit as st
import os
import tempfile
from extractor import extract_text_from_file
from analyzer import clasificar_documento, extraer_fun, extraer_informe_af, \
    extraer_compensacion, extraer_aptitud_suelo, extraer_costos, extraer_oficio, analizar_paquete
from vision_checker import verificar_imagenes_documento

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

    st.header("🖼️ Revisar imágenes de un doc")
    st.caption("Sube un PDF para verificar que sus mapas e imágenes coincidan con el texto.")
    pdf_vision = st.file_uploader(
        "PDF a revisar",
        type=["pdf", "docx", "doc"],
        key="vision_single"
    )
    tipo_vision = st.selectbox(
        "Tipo de documento",
        ["INFORME_AF", "FUN", "COMPENSACION", "APTITUD", "COSTOS", "OFICIO"],
        key="tipo_vision"
    )
    max_pags = st.slider("Máx. páginas a analizar", 1, 10, 4, key="max_pags_vision")
    btn_vision = st.button("🔍 Analizar imágenes", key="btn_vision")
    st.markdown("---")
    st.caption("Cotejo de datos: 100% local. Análisis visual de imágenes: requiere ANTHROPIC_API_KEY configurada.")

# ── ANÁLISIS VISUAL INDEPENDIENTE (sidebar) ──────────────────────────────────
if pdf_vision and btn_vision:
    from extractor import extract_text_from_file
    import tempfile, os
    st.markdown("---")
    st.subheader(f"🖼️ Análisis visual — {pdf_vision.name}")

    pdf_bytes = bytes(pdf_vision.getbuffer())
    suffix = os.path.splitext(pdf_vision.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        texto_doc = extract_text_from_file(tmp_path)
    finally:
        os.remove(tmp_path)

    with st.spinner("Analizando páginas con imágenes..."):
        hallazgos = verificar_imagenes_documento(pdf_bytes, texto_doc, tipo_vision, nombre_archivo=pdf_vision.name, max_paginas=max_pags)

    if not hallazgos:
        st.info("No se encontraron páginas con imágenes en este PDF, o PyMuPDF no está instalado (`pip install pymupdf`).")
    else:
        n_inc = sum(1 for h in hallazgos if h.get("inconsistencias"))
        if n_inc:
            st.error(f"⚠️ {n_inc} página(s) con posibles inconsistencias visuales.")
        else:
            st.success("✅ Sin inconsistencias visuales detectadas.")

        for h in hallazgos:
            tipo_icono = {"mapa": "🗺️", "tabla": "📊", "foto": "📷", "diagrama": "📐"}.get(h.get("tipo_imagen", ""), "🖼️")
            tiene_inc = bool(h.get("inconsistencias"))
            estado = "❌" if (h.get("coincide_con_texto") is False or tiene_inc) else ("✅" if h.get("coincide_con_texto") else "ℹ️")
            label = f"{estado} {tipo_icono} Página {h.get('pagina','?')} — {h.get('tipo_imagen','?')}"
            with st.expander(label, expanded=tiene_inc):
                st.markdown(f"**Descripción:** {h.get('descripcion', '—')}")
                if h.get("municipio_visible"):
                    st.markdown(f"**Municipio en imagen:** `{h['municipio_visible']}`")
                if h.get("departamento_visible"):
                    st.markdown(f"**Departamento en imagen:** `{h['departamento_visible']}`")
                if tiene_inc:
                    st.markdown("**Inconsistencias:**")
                    for inc in h["inconsistencias"]:
                        st.markdown(f"- ⚠️ {inc}")
                st.caption(f"Confianza: {h.get('confianza', '—')}")
    st.markdown("---")

# Carga de archivos
uploaded_files = st.file_uploader(
    "Sube los documentos del paquete forestal",
    accept_multiple_files=True,
    type=["pdf", "docx", "doc", "xlsx", "xls"]
)

if not uploaded_files:
    st.info("👆 Sube los documentos del paquete para validar, o usa el panel lateral para revisar imágenes de un doc.")

# ---------------------------------------------------------------------------
if uploaded_files:
    # EXTRACCIÓN Y CLASIFICACIÓN
    # ---------------------------------------------------------------------------
    st.markdown("---")
    st.subheader("1️⃣ Documentos detectados")
    
    documentos_texto = {}
    documentos_tipo = {}
    documentos_datos = {}
    documentos_pdfbytes = {}  # para análisis visual
    
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
            if suffix.lower() in (".pdf", ".docx", ".doc"):
                documentos_pdfbytes[file.name] = bytes(raw_bytes)
    
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
            doc_cols = ["FUN", "Informe AF", "Plan Comp.", "Aptitud", "Costos", "Oficio"]
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

            def colorear(val):
                if val == "❌":
                    return "background-color: #ffd6d6; color: #c0392b; font-weight: bold"
                if val == "✅":
                    return "background-color: #d6f5d6; color: #1e8449"
                return ""

            if df.empty:
                st.info("No se encontraron campos reconocibles en el documento.")
            else:
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

            # ── ANÁLISIS VISUAL DEL PAQUETE ───────────────────────────────────────
            pdfs_con_imagenes = {
                nombre: documentos_pdfbytes[nombre]
                for nombre, tipo in asignaciones.items()
                if nombre in documentos_pdfbytes
            }

            if pdfs_con_imagenes:
                st.markdown("---")
                st.subheader("5️⃣ Verificación visual de imágenes y mapas")
                st.caption("Se analiza cada página con imágenes usando IA.")

                hallazgos_totales = []
                for nombre, pdf_bytes_doc in pdfs_con_imagenes.items():
                    tipo_doc = asignaciones.get(nombre, "DESCONOCIDO")
                    texto_doc = documentos_texto.get(nombre, "")
                    with st.spinner(f"Analizando imágenes en {nombre}..."):
                        hallazgos = verificar_imagenes_documento(pdf_bytes_doc, texto_doc, tipo_doc, nombre_archivo=nombre, max_paginas=4)
                    for h in hallazgos:
                        h["archivo"] = nombre
                        hallazgos_totales.append(h)

                if not hallazgos_totales:
                    st.info("No se encontraron páginas con imágenes en los PDFs cargados.")
                else:
                    inc_visuales = [h for h in hallazgos_totales if h.get("inconsistencias")]
                    if inc_visuales:
                        st.error(f"⚠️ {sum(len(h['inconsistencias']) for h in inc_visuales)} inconsistencia(s) visual(es).")
                    else:
                        st.success("✅ Sin inconsistencias visuales.")

                    for h in hallazgos_totales:
                        tipo_icono = {"mapa": "🗺️", "tabla": "📊", "foto": "📷", "diagrama": "📐"}.get(h.get("tipo_imagen", ""), "🖼️")
                        tiene_inc = bool(h.get("inconsistencias"))
                        estado = "❌" if (h.get("coincide_con_texto") is False or tiene_inc) else ("✅" if h.get("coincide_con_texto") else "ℹ️")
                        label = f"{estado} {tipo_icono} {h['archivo']} — Pág. {h.get('pagina','?')} ({h.get('tipo_imagen','?')})"
                        with st.expander(label, expanded=tiene_inc):
                            st.markdown(f"**Descripción:** {h.get('descripcion', '—')}")
                            if h.get("municipio_visible"):
                                st.markdown(f"**Municipio en imagen:** `{h['municipio_visible']}`")
                            if h.get("departamento_visible"):
                                st.markdown(f"**Departamento en imagen:** `{h['departamento_visible']}`")
                            if tiene_inc:
                                st.markdown("**Inconsistencias:**")
                                for inc in h["inconsistencias"]:
                                    st.markdown(f"- ⚠️ {inc}")
                            st.caption(f"Confianza: {h.get('confianza', '—')}")

            with st.expander("🔧 Ver valores extraídos por documento (debug)", expanded=False):
                for tipo, datos in resultado["datos_crudos"].items():
                    st.markdown(f"**{LABELS.get(tipo, tipo)}**")
                    for k, v in datos.items():
                        if v:
                            st.markdown(f"- `{k}`: {v}")
