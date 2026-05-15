import streamlit as st
import os
import google.generativeai as genai
from extractor import extract_text_from_file

# --- Configuración de la página ---
st.set_page_config(
    page_title="ForestGuard Pro v3 - IA",
    page_icon="🌲",
    layout="wide"
)

# --- PROMPT DEL SISTEMA ---
SYSTEM_PROMPT = """
Eres un revisor técnico experto en permisos de aprovechamiento forestal para proyectos de energía solar en Colombia, con dominio de la normativa del Decreto 1076 de 2015 y los formatos de CORPOCESAR. Tu tarea es identificar TODAS las inconsistencias entre los documentos de un paquete forestal.

Se te proporcionan entre 4 y 5 documentos en texto plano. Debes extraer los valores clave de CADA documento y luego cruzarlos para detectar contradicciones.

---

## PASO 1 — EXTRACCIÓN DE DATOS POR DOCUMENTO

Para cada documento, localiza y extrae los siguientes valores. Cita el texto EXACTO de donde lo sacas (entre comillas) y el número de tabla o sección si existe.

### Del FUN (Formato Único Nacional):
- Número total de individuos a aprovechar: búscalo ÚNICAMENTE en la frase "Cantidad Total" al final de la tabla de especies. NUNCA uses los números de ítem, numerales de fila, ni coordenadas como cantidad de individuos.
- Volumen total en m³: en la misma frase "Cantidad Total", el valor expresado en "metros cúbicos de volumen total".
- Área del predio en ha: campo "Superficie (ha)" en la sección de información del predio.
- Costo de instalación del proyecto en pesos: campo "Costo del Proyecto, Obra o Actividad". Este es el ÚNICO costo que reporta el FUN.
- Municipio, departamento.
- Nombre del proyecto.

### Del Informe de Aprovechamiento y Reposición Forestal:
- Número total de individuos a aprovechar: búscalo en la introducción (frase "aprovechamiento de X árboles aislados") Y en la tabla de resumen por especie (fila "Total"). Reporta ambos valores y señala si difieren entre sí.
- Número de individuos a reponer: búscalo en la sección "Factor de Reposición" y en el párrafo introductorio de la sección "Costos de Reposición".
- Factor de reposición (número de árboles nuevos por árbol talado).
- Volumen total en m³: búscalo en cualquier tabla de resumen por especie y en la tabla de costos de aprovechamiento (columna Cantidad de la fila Tala).
- Área del proyecto en ha.
- Potencia nominal AC del proyecto en kW: búscala en la INTRODUCCIÓN y también en la sección "Descripción del área del proyecto". Reporta ambos valores por separado aunque sean iguales.
- Nombre de la empresa distribuidora de electricidad (Afinia, CENS, etc.).
- Nombre completo del título del documento tal como aparece en el encabezado principal.

### Del Informe de Aptitud del Suelo:
- Número de individuos mencionados (si aparece).
- Área del proyecto en ha.
- Potencia nominal del proyecto.
- Nombre de la empresa distribuidora de electricidad.
- Conclusión sobre vocación del suelo: copia el párrafo de conclusiones textualmente.
- Nombre completo del título del documento tal como aparece en el encabezado principal.

### Del Documento de Costos y Presupuesto:
- Número de individuos a aprovechar: búscalo en el párrafo introductorio de la sección de aprovechamiento, NO en columnas de cantidad de tablas de insumos ni en numerales de fila.
- Número de individuos a reponer: búscalo en el párrafo introductorio de la sección de reposición.
- Volumen total de aprovechamiento en m³: columna Cantidad de la fila "Tala" en la tabla de costos de aprovechamiento.
- Costo total de aprovechamiento forestal (COP): suma final de la tabla de costos de aprovechamiento.
- Costo total de compensación/reposición a 3 años (COP): suma final de la tabla de costos de reposición.
- Costo total de instalación del proyecto (COP): fila "TOTAL VALOR DEL PROYECTO" en la tabla de costos de implementación.
- Nombre completo del título del documento tal como aparece en el encabezado principal.

### Del Oficio de Solicitud:
- Número de individuos a aprovechar: búscalo en el párrafo "Para la implementación del proyecto, se requiere el aprovechamiento forestal de...".
- Nombre del proyecto tal como aparece.
- Distribuidora eléctrica mencionada.
- Potencia del proyecto mencionada.

---

## PASO 2 — TABLA DE COTEJO

Con los valores extraídos, construye una tabla comparativa con este formato exacto:

| Dato | FUN | Informe AF | Aptitud Suelo | Costos | Oficio | ¿Consistente? |
|---|---|---|---|---|---|---|

Filas obligatorias:
- Número de individuos a aprovechar
- Volumen total de aprovechamiento (m³)
- Número de individuos a reponer
- Área del predio (ha)
- Potencia AC del proyecto (kW)
- Costo de instalación del proyecto (COP)
- Costo aprovechamiento forestal (COP)
- Costo compensación/reposición (COP)
- Empresa distribuidora eléctrica
- Nombre del proyecto (en título del documento)

Reglas para marcar la columna "¿Consistente?":
- ✅ si todos los documentos que mencionan ese dato coinciden entre sí.
- ❌ si hay diferencia entre dos o más documentos que sí mencionan el dato.
- Si un documento no menciona el dato, escribe "—" en esa celda. La ausencia de un dato en un documento que no tiene obligación de reportarlo NO es una inconsistencia.

---

## PASO 3 — LISTADO DE INCOHERENCIAS

Para cada fila marcada con ❌ en la tabla, redacta un hallazgo con este formato:

**INCOHERENCIA #N — [Nombre del dato]**
- **Documentos afectados:** lista cuáles difieren
- **Valores encontrados:** indica exactamente qué dice cada documento
- **Texto fuente:** cita textualmente el fragmento de cada documento del que extrajiste el valor
- **Impacto regulatorio:** indica brevemente por qué esto puede generar observaciones de CORPOCESAR

Si encuentras el mismo dato con valores diferentes DENTRO de un mismo documento (por ejemplo, potencia AC en la introducción vs. en la descripción), repórtalo como incoherencia interna de ese documento con el mismo formato.

---

## PASO 4 — VERIFICACIÓN ARITMÉTICA

Verifica las siguientes operaciones y muestra el cálculo explícito:

1. **Factor de reposición:** individuos a reponer = individuos a aprovechar × factor de reposición declarado. ¿Cuadra?
2. **Costos de aprovechamiento:** Tala + Transporte menor = Total reportado. ¿Cuadra?
3. **Costos de reposición:** Mano de obra + Insumos + Herramientas + Reposición/mantenimiento + Imprevistos = Total reportado. ¿Cuadra?
4. **Costo total del proyecto:** Total inversión + Total operación = Total valor reportado. ¿Cuadra?

Para cada verificación muestra: operación realizada → resultado esperado → valor reportado → ✅ o ❌.

---

## PASO 5 — RESUMEN EJECUTIVO

Redacta un párrafo de máximo 6 líneas con las inconsistencias críticas que deben corregirse antes de radicar el paquete ante la autoridad ambiental.

---

## REGLAS IMPORTANTES:
1. Individuos en el FUN: el total está SOLO en "Cantidad Total" al final de la tabla.
2. Costos separados: el FUN solo reporta el costo de instalación. No lo confundas con aprovechamiento/compensación.
3. Áreas: unidad "ha" en sección predial.
4. Incoherencias internas: reportar si el mismo dato varía en el mismo documento.
5. Ausencia no es error: si un doc no debe reportar un dato, usa "—" y no marques error.
"""

# --- UI PRINCIPAL ---

st.title("🌲 ForestGuard Pro - Auditor de IA")
st.markdown("Validador avanzado de informes ambientales impulsado por **Google Gemini**.")

# Configuración API Key en Sidebar
with st.sidebar:
    st.header("Configuración")
    
    # Intentar leer desde secrets primero (para Streamlit Cloud)
    api_key = ""
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("API Key cargada desde la nube.")
    except Exception:
        api_key = st.text_input("Ingresa tu API Key de Google Gemini:", type="password")
        if not api_key:
            st.warning("⚠️ Debes proporcionar una API Key para utilizar el análisis inteligente.")
            st.markdown("[Obtén una clave gratis aquí](https://aistudio.google.com/app/apikey)")

    st.markdown("---")
    st.markdown("""
    ### Documentos soportados
    - Formato Único Nacional (FUN)
    - Informe Aprovechamiento
    - Aptitud de Suelo
    - Costos y Presupuestos
    - Oficio de Solicitud
    *(PDF, DOCX, XLSX)*
    """)

# Zona de carga de archivos
uploaded_files = st.file_uploader("Sube todos los documentos del paquete forestal aquí", accept_multiple_files=True, type=['pdf', 'docx', 'doc', 'xlsx', 'xls'])

if st.button("🚀 Iniciar Análisis Experto", type="primary"):
    if not api_key:
        st.error("No se puede iniciar el análisis sin una API Key válida.")
        st.stop()
    
    if not uploaded_files:
        st.error("Por favor, sube al menos un documento para analizar.")
        st.stop()
        
    try:
        genai.configure(api_key=api_key)
        # Usar el modelo Pro para tareas complejas
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
    except Exception as e:
        st.error(f"Error configurando la API: {str(e)}")
        st.stop()

    # Procesar archivos
    os.makedirs("temp", exist_ok=True)
    
    with st.status("Analizando documentos...", expanded=True) as status:
        document_texts = []
        
        st.write("1️⃣ Extrayendo texto de los documentos...")
        for file in uploaded_files:
            temp_path = os.path.join("temp", file.name)
            with open(temp_path, "wb") as f:
                f.write(file.getbuffer())
                
            try:
                extracted_text = extract_text_from_file(temp_path)
                document_texts.append(f"\n=======================\nDOCUMENTO: {file.name}\n=======================\n{extracted_text}")
                st.write(f"- ✔️ Extraído: {file.name}")
            except Exception as e:
                st.write(f"- ❌ Error extrayendo {file.name}: {str(e)}")
            finally:
                # Limpiar temporal
                try:
                    os.remove(temp_path)
                except:
                    pass
        
        all_text_combined = "\n".join(document_texts)
        
        st.write("2️⃣ Ejecutando el Auditor Técnico de IA (Gemini 1.5 Pro)...")
        # Mostrar el texto original en un expander
        with st.expander("Ver Texto Original Extraído (Debug)"):
            st.text(all_text_combined)

        try:
            full_prompt = f"{SYSTEM_PROMPT}\n\nAquí tienes el contenido de los documentos extraídos para analizar:\n\n{all_text_combined}"
            
            response = model.generate_content(full_prompt)
            
            status.update(label="Análisis completado", state="complete", expanded=False)
            
            # Mostrar Resultados
            st.divider()
            st.header("📊 Resultados del Análisis")
            st.markdown(response.text)
            
        except Exception as e:
            status.update(label="Error en el análisis", state="error")
            st.error(f"Error comunicándose con Gemini: {str(e)}")
