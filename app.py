import streamlit as st
import os
import tempfile
from extractor import extract_text_from_file
from analyzer import clasificar_documento, extraer_fun, extraer_informe_af, \
    extraer_compensacion, extraer_aptitud_suelo, extraer_costos, extraer_oficio, \
    extraer_inventario, analizar_paquete
from resaltado_checker import detectar_resaltado_documento
from fecha_checker import extraer_fecha_documento, evaluar_vigencia
from propietario_checker import verificar_propietario_inventario

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
    documentos_resaltado = {}
    documentos_vigencia = {}

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

            # Resaltado amarillo (texto e imágenes) — convención interna para
            # marcar datos pendientes antes de radicar
            try:
                documentos_resaltado[file.name] = detectar_resaltado_documento(tmp_path, file.name)
            except Exception:
                documentos_resaltado[file.name] = {"texto": [], "imagenes": [], "anotaciones_pdf": [], "tiene_hallazgos": False}

            # Fecha del encabezado y qué tan desactualizada está
            try:
                fecha_doc = extraer_fecha_documento(tmp_path, file.name)
                documentos_vigencia[file.name] = evaluar_vigencia(fecha_doc)
            except Exception:
                documentos_vigencia[file.name] = {"estado": "sin_fecha", "dias": None, "fecha": None}

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

    ESTADO_VIGENCIA_LABEL = {
        "vigente": "🟢 vigente",
        "revisar": "🟡 revisar antigüedad",
        "desactualizado": "🔴 desactualizado",
        "fecha_futura": "🟡 fecha futura (revisar)",
        "sin_fecha": "⚪ sin fecha detectada",
    }

    cols = st.columns([3, 2, 2, 2])
    with cols[0]:
        st.markdown("**Archivo**")
    with cols[1]:
        st.markdown("**Tipo detectado** (puedes corregir)")
    with cols[2]:
        st.markdown("**Fecha encabezado**")
    with cols[3]:
        st.markdown("**Resaltado amarillo**")

    for nombre, tipo_auto in documentos_tipo.items():
        c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
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
        with c3:
            vig = documentos_vigencia.get(nombre, {})
            if vig.get("fecha"):
                dias = vig["dias"]
                st.markdown(
                    f"{ESTADO_VIGENCIA_LABEL.get(vig['estado'], '⚪')}<br>"
                    f"<span style='font-size:12px;color:#666;'>{vig['fecha'].strftime('%d/%m/%Y')} · hace {dias} días</span>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(ESTADO_VIGENCIA_LABEL["sin_fecha"])
        with c4:
            res = documentos_resaltado.get(nombre, {})
            n_hallazgos = len(res.get("texto", [])) + len(res.get("imagenes", [])) + len(res.get("anotaciones_pdf", []))
            if n_hallazgos > 0:
                st.markdown(f"🟨 **{n_hallazgos}** hallazgo(s)")
            else:
                st.markdown("—")

    for nombre, tipo in asignaciones.items():
        if tipo in EXTRACTORES and documentos_texto.get(nombre):
            datos = EXTRACTORES[tipo](documentos_texto[nombre])
            documentos_datos[tipo] = datos

    # ---------------------------------------------------------------------------
    # DETALLE: RESALTADO AMARILLO Y VIGENCIA DE FECHAS
    # ---------------------------------------------------------------------------
    archivos_con_resaltado = [n for n, r in documentos_resaltado.items() if r.get("tiene_hallazgos")]
    archivos_desactualizados = [
        n for n, v in documentos_vigencia.items()
        if v.get("estado") in ("desactualizado", "revisar", "fecha_futura")
    ]

    if archivos_con_resaltado:
        st.markdown("---")
        with st.expander(f"🟨 Resaltado amarillo detectado en {len(archivos_con_resaltado)} documento(s) — datos pendientes por confirmar", expanded=True):
            for nombre in archivos_con_resaltado:
                res = documentos_resaltado[nombre]
                st.markdown(f"**📎 {nombre}**")

                # Agrupar TODO por sección para no repetir el título en cada
                # fragmento/celda (una tabla con 12 celdas resaltadas debe
                # verse como 1 aviso por sección, no 12 líneas idénticas).
                por_seccion = {}

                def _bucket(seccion):
                    clave = seccion or "Sección no identificada"
                    return por_seccion.setdefault(clave, {"parrafos_tablas": [], "imagenes": [], "anotaciones": []})

                for h in res.get("texto", []):
                    _bucket(h.get("seccion"))["parrafos_tablas"].append(h)
                for h in res.get("imagenes", []):
                    _bucket(h.get("seccion"))["imagenes"].append(h)
                for h in res.get("anotaciones_pdf", []):
                    _bucket(h.get("seccion"))["anotaciones"].append(h)

                for seccion, grupos in por_seccion.items():
                    st.markdown(f"**📌 {seccion}**")

                    if grupos["parrafos_tablas"]:
                        por_ubicacion = {}
                        for h in grupos["parrafos_tablas"]:
                            por_ubicacion.setdefault(h["ubicacion"], []).append(h["texto_resaltado"])
                        for ubicacion, valores in por_ubicacion.items():
                            ejemplos = ", ".join(f'"{v}"' for v in valores[:3])
                            extra = f" y {len(valores) - 3} más" if len(valores) > 3 else ""
                            st.markdown(f"- 📝 {ubicacion} — {len(valores)} fragmento(s) resaltado(s) (ej: {ejemplos}{extra})")

                    for h in grupos["imagenes"]:
                        if "pagina" in h:
                            st.markdown(f"- 🖼️ Página {h['pagina']} con resaltado")
                        else:
                            st.markdown(f"- 🖼️ Imagen con resaltado ({h['ubicacion']})")

                    for h in grupos["anotaciones"]:
                        comentario = f" — nota: \"{h['comentario']}\"" if h.get("comentario") else ""
                        st.markdown(f"- 🖊️ Anotación de resaltado — página {h['pagina']}{comentario}")

            st.caption("Revisa estas zonas antes de radicar: el resaltado amarillo suele indicar un dato que falta confirmar.")

    if archivos_desactualizados:
        st.markdown("---")
        with st.expander(f"🕒 {len(archivos_desactualizados)} documento(s) con fecha de encabezado a revisar", expanded=True):
            for nombre in archivos_desactualizados:
                vig = documentos_vigencia[nombre]
                if vig["estado"] == "desactualizado":
                    st.markdown(f"🔴 **{nombre}** — fecha del {vig['fecha'].strftime('%d/%m/%Y')}, hace **{vig['dias']} días** (más de un año). Verifica si sigue vigente.")
                elif vig["estado"] == "revisar":
                    st.markdown(f"🟡 **{nombre}** — fecha del {vig['fecha'].strftime('%d/%m/%Y')}, hace **{vig['dias']} días**. Confirma si el trámite tiene un plazo de vigencia menor.")
                elif vig["estado"] == "fecha_futura":
                    st.markdown(f"🟡 **{nombre}** — se detectó una fecha futura ({vig['fecha'].strftime('%d/%m/%Y')}); revisa si es un error de formato o una fecha de vigencia/vencimiento.")
            st.caption("Umbral por defecto: >180 días 'revisar', >365 días 'desactualizado'. Ajusta el umbral en fecha_checker.py si tu trámite tiene otro plazo.")

    # ---------------------------------------------------------------------------
    # PROPIETARIO: INVENTARIO vs. PLAN/INFORME DE APROVECHAMIENTO
    # ---------------------------------------------------------------------------
    archivos_inventario = [n for n, t in asignaciones.items() if t == "INVENTARIO"]
    archivos_informe_af = [n for n, t in asignaciones.items() if t == "INFORME_AF"]

    if archivos_inventario and archivos_informe_af:
        st.markdown("---")
        buffers = {f.name: f for f in uploaded_files}
        alertas_propietario = []

        for nombre_inv in archivos_inventario:
            for nombre_af in archivos_informe_af:
                tmp_inv = tmp_af = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as t1:
                        t1.write(buffers[nombre_inv].getbuffer())
                        tmp_inv = t1.name
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as t2:
                        t2.write(buffers[nombre_af].getbuffer())
                        tmp_af = t2.name

                    resultado = verificar_propietario_inventario(tmp_inv, tmp_af)
                    alertas_propietario.append((nombre_inv, nombre_af, resultado))
                except Exception as e:
                    st.warning(f"No se pudo comparar propietario entre {nombre_inv} y {nombre_af}: {e}")
                finally:
                    for p in (tmp_inv, tmp_af):
                        if p and os.path.exists(p):
                            os.remove(p)

        hay_error = any(r["coincide"] is False for _, _, r in alertas_propietario)
        with st.expander(
            f"👤 Verificación de propietario (Inventario vs. Plan de Aprovechamiento)",
            expanded=hay_error
        ):
            for nombre_inv, nombre_af, r in alertas_propietario:
                if r["coincide"] is None:
                    st.markdown(
                        f"⚪ No se pudo determinar el propietario en **{nombre_inv}** y/o **{nombre_af}** "
                        f"— revisa manualmente."
                    )
                elif r["coincide"]:
                    st.markdown(
                        f"🟢 **{nombre_inv}** — el propietario (\"{r['propietario_inventario']}\") "
                        f"coincide con el del plan de aprovechamiento (**{nombre_af}**)."
                    )
                else:
                    nombres_plan = ", ".join(p["nombre"] for p in r["propietarios_plan"]) or "ninguno detectado"
                    st.markdown(
                        f"🔴 **{nombre_inv}**: el campo PROPIETARIO dice \"**{r['propietario_inventario']}**\", "
                        f"pero **{nombre_af}** identifica como propietario a **\"{nombres_plan}\"**. "
                        f"El PROPIETARIO del inventario nunca debe ser Unergy/el solicitante/el contratista — "
                        f"debe ser el dueño real del predio que autoriza el aprovechamiento."
                    )
            st.caption("Se compara por similitud de texto (nombres abreviados o con tildes/errores menores se consideran coincidencia).")

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
