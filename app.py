import streamlit as st
import pandas as pd
import os
import shutil
import tempfile
from document_processor import process_document
from ai_extractor import extract_metadata_and_summary, generate_embedding
import database

st.set_page_config(page_title="Base de Datos Municipal", layout="wide", page_icon="🏛️")

# Initialize DB if not exists
database.init_db()

st.title("🏛️ Sistema de Gestión de Normativas Municipales")

tab1, tab2, tab3 = st.tabs(["📤 Procesar Documentos", "🗃️ Explorar Base de Datos", "🔍 Búsqueda Semántica"])

with tab1:
    st.header("Cargar y Procesar Normativas")
    st.write("Sube archivos PDF o DOCX. El sistema extraerá el texto, utilizará IA para entender los metadatos y los guardará en la base de datos.")
    
    uploaded_files = st.file_uploader("Seleccionar archivos", type=["pdf", "docx"], accept_multiple_files=True)
    
    # Engine selector
    st.subheader("Configuración de IA")
    ia_engine = st.radio("Selecciona el motor de Inteligencia Artificial para extraer los datos:", 
                         options=["DeepSeek (Recomendado - Menos límites)", "Google Gemini (Plan Gratuito)"])
    
    if st.button("Procesar Archivos", type="primary"):
        if not uploaded_files:
            st.warning("Por favor, sube al menos un archivo.")
        elif ia_engine == "Google Gemini (Plan Gratuito)" and not os.getenv("GOOGLE_API_KEY"):
            st.error("⚠️ Falta configurar GOOGLE_API_KEY en el archivo .env")
        elif ia_engine == "DeepSeek (Recomendado - Menos límites)" and not os.getenv("DEEPSEEK_API_KEY"):
            st.error("⚠️ Falta configurar DEEPSEEK_API_KEY en el archivo .env")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, file in enumerate(uploaded_files):
                status_text.text(f"Procesando: {file.name} ({i+1}/{len(uploaded_files)})")
                try:
                    # Save to temp file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.name)[1]) as tmp_file:
                        tmp_file.write(file.read())
                        tmp_path = tmp_file.name

                    # 1. Extract Text
                    texto_completo = process_document(tmp_path)
                    
                    if not texto_completo:
                        st.error(f"No se pudo extraer texto de {file.name}")
                        continue
                    
                    # 2. Extract Metadata via AI
                    status_text.text(f"Extrayendo metadatos con IA ({'DeepSeek' if 'DeepSeek' in ia_engine else 'Gemini'}): {file.name}")
                    if "DeepSeek" in ia_engine:
                        from ai_extractor_deepseek import extract_metadata_and_summary_deepseek
                        metadata = extract_metadata_and_summary_deepseek(texto_completo)
                    else:
                        metadata = extract_metadata_and_summary(texto_completo)
                    
                    # 3. Generate Embedding (Local)
                    status_text.text(f"Generando vector de búsqueda (Modelo Local sin límites): {file.name}")
                    embedding = generate_embedding(texto_completo)
                    
                    # 4. Save to DB
                    database.insert_normativa(metadata, texto_completo, file.name, embedding)
                    
                    st.success(f"✅ {file.name} procesado correctamente. (Norma: {metadata.get('numero', 'N/A')} - {metadata.get('tipo_nombre', 'N/A')})")
                    
                    # Clean up
                    os.unlink(tmp_path)
                    
                    if len(uploaded_files) > 1 and i < len(uploaded_files) - 1:
                        if "Google" in ia_engine:
                            status_text.text(f"Esperando 60 segundos para no exceder el límite gratuito de Google...")
                            import time
                            time.sleep(60)
                        else:
                            # DeepSeek es mucho más permisivo, solo esperamos 1 segundo por cortesía
                            import time
                            time.sleep(1)
                            
                except Exception as e:
                    # Si es un error de reintentos de Tenacity, sacamos el error real que está adentro
                    from tenacity import RetryError
                    if isinstance(e, RetryError):
                        real_error = e.last_attempt.exception()
                        error_msg = str(real_error)
                    else:
                        error_msg = str(e)
                        
                    if "ResourceExhausted" in error_msg or "429" in error_msg:
                        st.error(f"❌ Error al procesar {file.name}: Límite de cuota gratuita superado (ResourceExhausted). Intenta más tarde o procesa este documento manualmente.")
                    elif "InvalidArgument" in error_msg or "400" in error_msg:
                        st.error(f"❌ Error al procesar {file.name}: El archivo contiene datos que la IA no pudo procesar (InvalidArgument). Es posible que el texto extraído contenga caracteres corruptos o no sea compatible con la API. Error técnico: {error_msg}")
                    else:
                        st.error(f"❌ Error al procesar {file.name}: {error_msg}")
                
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            status_text.text("¡Procesamiento finalizado!")

with tab2:
    st.header("Base de Datos de Normativas")
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
    with col_btn1:
        if st.button("🔄 Actualizar Tabla"):
            pass # Streamlit reruns the script anyway
    with col_btn2:
        if 'edit_mode' not in st.session_state:
            st.session_state.edit_mode = False
        if st.button("✏️ Modificar Tabla"):
            st.session_state.edit_mode = not st.session_state.edit_mode
    with col_btn3:
        if st.button("⚠️ Reiniciar Tabla"):
            st.session_state.show_reset_confirm = True

    if st.session_state.get('show_reset_confirm'):
        st.warning("¿Estás seguro? Esto borrará TODA la base de datos (SQLite y ChromaDB) de forma irreversible.")
        col_y, col_n = st.columns(2)
        if col_y.button("Sí, borrar todo", type="primary"):
            database.reset_database()
            st.session_state.show_reset_confirm = False
            st.success("Base de datos reiniciada. Refresca la página.")
        if col_n.button("No, cancelar"):
            st.session_state.show_reset_confirm = False
    
    normativas = database.get_all_normativas()
    
    if normativas:
        df = pd.DataFrame(normativas)
        # Reorder and filter columns for display
        display_df = df[['id', 'numero', 'tipo_nombre', 'titulo', 'categoria_nombre', 'fecha', 'vigente', 'resumen_ia']]
        
        if st.session_state.get('edit_mode'):
            st.info("Modo Edición: Modifica los valores directamente en la tabla y presiona 'Guardar' abajo.")
            edited_df = st.data_editor(display_df, use_container_width=True)
            if st.button("💾 Guardar Modificaciones de la Tabla", type="primary"):
                for index, row in edited_df.iterrows():
                    updated_data = {
                        "numero": str(row['numero']) if pd.notnull(row['numero']) else "",
                        "titulo": str(row['titulo']) if pd.notnull(row['titulo']) else "",
                        "tipo_nombre": str(row['tipo_nombre']) if pd.notnull(row['tipo_nombre']) else "",
                        "categoria_nombre": str(row['categoria_nombre']) if pd.notnull(row['categoria_nombre']) else "",
                        "fecha": str(row['fecha']) if pd.notnull(row['fecha']) else "",
                        "resumen_ia": str(row['resumen_ia']) if pd.notnull(row['resumen_ia']) else "",
                        "vigente": bool(row['vigente'])
                    }
                    database.update_normativa(int(row['id']), updated_data)
                st.success("Cambios guardados en la base de datos.")
                st.session_state.edit_mode = False
        else:
            st.dataframe(display_df, use_container_width=True)
        
        # Detail view
        st.subheader("Ver Detalle / Editar")
        selected_id = st.selectbox("Seleccionar ID de norma para ver detalles:", df['id'])
        if selected_id:
            detail = df[df['id'] == selected_id].iloc[0]
            
            # Use tabs for View and Edit
            v_tab, e_tab = st.tabs(["Ver Información", "Editar Registro"])
            
            with v_tab:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Número:** {detail['numero']}")
                    st.markdown(f"**Tipo:** {detail['tipo_nombre']}")
                    st.markdown(f"**Fecha:** {detail['fecha']}")
                    st.markdown(f"**Estado:** {'Vigente' if detail['vigente'] else 'No Vigente/Derogada'}")
                    st.markdown(f"**Categoría:** {detail['categoria_nombre']}")
                with col2:
                    st.markdown(f"**Título Oficial:** {detail['titulo']}")
                    st.markdown(f"**Resumen IA:** {detail['resumen_ia']}")
                
                with st.expander("Ver Texto Completo Extraído"):
                    st.text(detail['texto_completo'])
                    
                if st.button("🗑️ Eliminar Norma", type="primary", use_container_width=True):
                    database.delete_normativa(int(selected_id))
                    st.success("Norma eliminada exitosamente. Actualiza la tabla.")
            
            with e_tab:
                with st.form("edit_form"):
                    st.write("Modifica los datos y guarda los cambios.")
                    new_numero = st.text_input("Número", value=str(detail['numero'] if detail['numero'] else ""))
                    new_titulo = st.text_input("Título Oficial", value=str(detail['titulo'] if detail['titulo'] else ""))
                    new_tipo = st.text_input("Tipo", value=str(detail['tipo_nombre'] if detail['tipo_nombre'] else ""))
                    new_cat = st.text_input("Categoría", value=str(detail['categoria_nombre'] if detail['categoria_nombre'] else ""))
                    new_fecha = st.text_input("Fecha", value=str(detail['fecha'] if detail['fecha'] else ""))
                    new_resumen = st.text_area("Resumen IA", value=str(detail['resumen_ia'] if detail['resumen_ia'] else ""))
                    new_vigente = st.checkbox("Vigente", value=bool(detail['vigente']))
                    
                    if st.form_submit_button("Guardar Cambios"):
                        updated_data = {
                            "numero": new_numero,
                            "titulo": new_titulo,
                            "tipo_nombre": new_tipo,
                            "categoria_nombre": new_cat,
                            "fecha": new_fecha,
                            "resumen_ia": new_resumen,
                            "vigente": new_vigente
                        }
                        database.update_normativa(int(selected_id), updated_data)
                        st.success("¡Datos actualizados! Actualiza la tabla para ver los cambios.")
    else:
        st.info("La base de datos está vacía. Procesa algunos documentos primero.")

with tab3:
    st.header("Búsqueda Semántica con IA")
    st.write("Escribe una pregunta o tema en lenguaje natural. La IA buscará en el significado del texto, no solo palabras clave.")
    
    query = st.text_input("¿Qué estás buscando? (Ej. 'Normativas sobre estacionamiento medido')")
    
    if st.button("Buscar", type="primary") and query:
        if not os.getenv("GOOGLE_API_KEY"):
            st.error("⚠️ Falta configurar GOOGLE_API_KEY en el archivo .env")
        else:
            with st.spinner("Generando vector de búsqueda y consultando ChromaDB..."):
                try:
                    # Generar embedding para la query usando el mismo modelo
                    query_embedding = generate_embedding(query)
                    
                    # Buscar en ChromaDB
                    results = database.search_normativas(query_embedding, n_results=5)
                    
                    if results and results['ids'] and len(results['ids'][0]) > 0:
                        st.success(f"Se encontraron {len(results['ids'][0])} resultados relevantes.")
                        
                        for i in range(len(results['ids'][0])):
                            st.markdown(f"### Resultado {i+1}")
                            meta = results['metadatas'][0][i]
                            st.markdown(f"**Norma Número:** {meta.get('numero', 'N/A')} - **Título:** {meta.get('titulo', 'N/A')}")
                            # Mostrar un fragmento del documento
                            texto_completo = results['documents'][0][i]
                            st.markdown(f"**Fragmento:** _{texto_completo[:500]}..._")
                            st.divider()
                    else:
                        st.info("No se encontraron resultados muy similares.")
                except Exception as e:
                    st.error(f"Error en la búsqueda: {e}")
