import streamlit as st
import pandas as pd
import os
import shutil
import tempfile
import datetime
from document_processor import process_document
from ai_extractor import extract_metadata_and_summary, generate_embedding
import database

st.set_page_config(page_title="Base de Datos Municipal", layout="wide", page_icon="🏛️")

# Initialize DB if not exists
database.init_db()

st.title("🏛️ Sistema de Gestión de Normativas Municipales")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📤 Procesar Documentos", "🗃️ Explorar Base de Datos", "🔍 Búsqueda Semántica", "🕸️ Mapa de Conexiones", "⚖️ Relaciones Jurídicas"])

with tab1:
    st.header("Cargar y Procesar Normativas")
    st.write("Sube archivos PDF o DOCX. El sistema extraerá el texto, utilizará IA para entender los metadatos y los guardará en la base de datos.")
    
    uploaded_files = st.file_uploader("Seleccionar archivos", type=["pdf", "docx", "doc", "jpg", "jpeg", "png"], accept_multiple_files=True)
    
    # Engine selector
    st.subheader("Configuración de IA")
    ia_engine = st.radio("Selecciona el motor de Inteligencia Artificial para extraer los datos:", 
                         options=["DeepSeek (Recomendado - Menos límites)", "OpenAI GPT-4o-mini (Rápido y Estable)", "Google Gemini (Plan Gratuito)"])
    
    if st.button("Procesar Archivos", type="primary"):
        if not uploaded_files:
            st.warning("Por favor, sube al menos un archivo.")
        elif ia_engine == "Google Gemini (Plan Gratuito)" and not os.getenv("GOOGLE_API_KEY"):
            st.error("⚠️ Falta configurar GOOGLE_API_KEY en el archivo .env")
        elif ia_engine == "DeepSeek (Recomendado - Menos límites)" and not os.getenv("DEEPSEEK_API_KEY"):
            st.error("⚠️ Falta configurar DEEPSEEK_API_KEY en el archivo .env")
        elif "OpenAI" in ia_engine and not os.getenv("OPENAI_API_KEY"):
            st.error("⚠️ Falta configurar OPENAI_API_KEY en el archivo .env")
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
                    texto_completo = process_document(tmp_path, ia_engine)
                    
                    if not texto_completo:
                        st.error(f"No se pudo extraer texto de {file.name}")
                        continue
                    
                    # 2. Extract Metadata via AI
                    status_text.text(f"Extrayendo metadatos con IA ({ia_engine}): {file.name}")
                    if "DeepSeek" in ia_engine:
                        from ai_extractor_deepseek import extract_metadata_and_summary_deepseek
                        metadata = extract_metadata_and_summary_deepseek(texto_completo)
                    elif "OpenAI" in ia_engine:
                        from ai_extractor_openai import extract_metadata_and_summary_openai
                        metadata = extract_metadata_and_summary_openai(texto_completo)
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
                            # OpenAI y DeepSeek son rápidos
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
            
    # Botón para retroactivo
    col_back1, col_back2 = st.columns(2)
    with col_back1:
        if st.button("🤖 Segmentar Artículos de Documentos Antiguos (OpenAI)", use_container_width=True):
            with st.spinner("Llamando a OpenAI para estructurar documentos antiguos... Revisa la consola negra para ver el progreso detallado. Puede tardar varios minutos."):
                import subprocess
                subprocess.Popen(["venv\\Scripts\\python.exe", "backfill_articulos.py", "--engine", "OpenAI"])
                st.success("¡Proceso de segmentación iniciado en segundo plano! Revisa la consola negra.")
    with col_back2:
        if st.button("⛓️ Calcular Vigencias y Consolidar Textos (OpenAI)", use_container_width=True):
            with st.spinner("Llamando a OpenAI para consolidar textos modificados... Revisa la consola negra para ver el progreso detallado."):
                import subprocess
                subprocess.Popen(["venv\\Scripts\\python.exe", "consolidator.py"])
                st.success("¡Proceso de consolidación iniciado en segundo plano! Revisa la consola negra.")
    
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
            
            st.download_button(
                label="📥 Descargar Base Completa (CSV / Excel)",
                data=df.to_csv(index=False).encode('utf-8'),
                file_name='base_datos_municipal_completa.csv',
                mime='text/csv',
                help="Descarga un archivo con todas las columnas, incluyendo el texto extraído completo de cada normativa."
            )
        
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
                
                st.subheader("Estructura de la Norma y Línea de Tiempo")
                
                # Selector de fecha para línea de tiempo
                usar_timeline = st.checkbox("🔍 Habilitar Línea de Tiempo Histórica")
                fecha_filtro = None
                if usar_timeline:
                    selected_date = st.date_input("Ver estado de los artículos en esta fecha:", value=datetime.date.today())
                    fecha_filtro = selected_date.strftime('%Y-%m-%d')
                    st.info(f"Mostrando versión de los artículos tal cual regían el {fecha_filtro}.")
                
                articulos_db = database.get_articulos_por_norma(int(selected_id), fecha=fecha_filtro)
                if articulos_db:
                    st.success(f"Se encontraron {len(articulos_db)} artículos/secciones activos.")
                    for art in articulos_db:
                        # Badge de estado temporal
                        if not art.get('fecha_hasta'):
                            badge = f"🟢 Vigente hoy (v{art['version_numero']})"
                        else:
                            badge = f"🔴 Modificado/Derogado (Vigente {art['fecha_desde']} a {art['fecha_hasta']})"
                            
                        with st.expander(f"Artículo {art['numero']} — {badge}"):
                            st.write(art['texto'])
                            
                            # Mostrar historial de versiones si hay más de una
                            historial = database.get_historial_articulo(int(selected_id), art['numero'])
                            if len(historial) > 1:
                                st.markdown("---")
                                st.markdown("**Historial de versiones de este artículo:**")
                                for h in historial:
                                    ver_badge = "Creación original" if h['version_numero'] == 1 else f"Modificación por {h['fuente_norma_tipo']} Nº {h['fuente_norma_numero']}"
                                    periodo = f"Vigencia: {h['fecha_desde']}" + (f" hasta {h['fecha_hasta']}" if h['fecha_hasta'] else " en adelante (Activo)")
                                    st.markdown(f"* **v{h['version_numero']}** — *{ver_badge}* ({periodo})")
                                    st.caption(f"*Texto:* {h['texto'][:250]}...")
                else:
                    st.info("Este documento no está estructurado en artículos o no estaba vigente en la fecha seleccionada.")
                
                with st.expander("Ver Documento Original Crudo (Sin estructurar)"):
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

with tab4:
    st.header("🕸️ Mapa de Conexiones (Grafo)")
    st.write("Visualiza cómo las normativas se referencian entre sí.")
    
    col_g1, col_g2 = st.columns([3, 1])
    
    with col_g2:
        st.subheader("Herramientas")
        if st.button("🔄 Generar / Actualizar Mapa", type="primary", use_container_width=True):
            with st.spinner("Dibujando conexiones..."):
                from network_graph import generate_network_graph
                html_data = generate_network_graph()
                st.session_state['graph_html'] = html_data
                
        st.divider()
        st.write("Usa DeepSeek u OpenAI para escanear documentos que fueron subidos antes de implementar el mapa.")
        if st.button("🔍 Escanear documentos antiguos", use_container_width=True):
            api_choice = "DeepSeek" if os.getenv("DEEPSEEK_API_KEY") else ("OpenAI" if os.getenv("OPENAI_API_KEY") else None)
            if not api_choice:
                st.error("⚠️ Necesitas configurar DEEPSEEK_API_KEY u OPENAI_API_KEY en .env")
            else:
                normativas = database.get_all_normativas()
                import json
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # Filtrar normativas sin referencias
                viejas = [n for n in normativas if not n.get('referencias') or n.get('referencias') == '[]' or n.get('referencias') == 'None']
                
                for i, norma in enumerate(viejas):
                    status_text.text(f"Escaneando Norma {norma['numero']} ({i+1}/{len(viejas)}) con {api_choice}...")
                    try:
                        if api_choice == "DeepSeek":
                            from ai_extractor_deepseek import extract_metadata_and_summary_deepseek
                            metadata = extract_metadata_and_summary_deepseek(norma['texto_completo'])
                        else:
                            from ai_extractor_openai import extract_metadata_and_summary_openai
                            metadata = extract_metadata_and_summary_openai(norma['texto_completo'])
                            
                        refs = metadata.get('referencias', [])
                        rels = metadata.get('relaciones_juridicas', [])
                        
                        # Actualizar en BD
                        database.update_normativa(norma['id'], {
                            "referencias": json.dumps(refs),
                            "relaciones_juridicas": json.dumps(rels)
                        })
                    except Exception as e:
                        pass
                    progress_bar.progress((i + 1) / len(viejas))
                
                status_text.text("¡Escaneo completo! Actualiza el mapa para ver las nuevas conexiones.")
                st.success(f"Se escanearon {len(viejas)} documentos antiguos con {api_choice}.")
                
    with col_g1:
        if 'graph_html' in st.session_state:
            import streamlit.components.v1 as components
            components.html(st.session_state['graph_html'], height=650)
        else:
            st.info("👈 Haz clic en 'Generar Mapa' para ver las conexiones.")

with tab5:
    st.header("⚖️ Relaciones Jurídicas")
    st.write("Listado detallado de las acciones legales (modificaciones, derogaciones, etc.) que ejercen unas normas sobre otras.")
    
    normativas = database.get_all_normativas()
    
    # Extraer todas las relaciones a una lista plana para armar una tabla
    relaciones_planas = []
    import json
    
    for norma in normativas:
        rels_str = norma.get('relaciones_juridicas')
        if rels_str and rels_str != '[]' and rels_str != 'None':
            try:
                rels = json.loads(rels_str)
                for r in rels:
                    relaciones_planas.append({
                        "Norma Origen": norma.get('numero', 'N/A'),
                        "Acción Jurídica": str(r.get('accion', '')).upper(),
                        "Norma Destino": r.get('norma_destino', 'N/A'),
                        "Detalle": r.get('detalle', '')
                    })
            except Exception:
                pass
                
    if relaciones_planas:
        df_rels = pd.DataFrame(relaciones_planas)
        # Colorear acciones en la tabla
        def highlight_action(val):
            color = ''
            v = str(val).lower()
            if 'deroga' in v:
                color = 'color: #f44336; font-weight: bold;'
            elif 'modifica' in v or 'sustituye' in v or 'corrige' in v:
                color = 'color: #ff9800; font-weight: bold;'
            elif 'reglamenta' in v or 'aprueba' in v or 'complementa' in v:
                color = 'color: #4CAF50; font-weight: bold;'
            return color
            
        st.dataframe(df_rels.style.map(highlight_action, subset=['Acción Jurídica']), use_container_width=True)
        
        col_csv, _ = st.columns([1, 4])
        with col_csv:
            st.download_button(
                label="📥 Exportar Relaciones (CSV)",
                data=df_rels.to_csv(index=False).encode('utf-8'),
                file_name='relaciones_juridicas.csv',
                mime='text/csv'
            )
            
        st.divider()
        st.subheader("🕸️ Mapa de Relaciones Jurídicas Puras")
        st.write("Este mapa excluye las menciones simples y **sólo muestra normativas que se modifican, derogan o reglamentan entre sí**.")
        if st.button("🔄 Generar Mapa de Acciones", type="primary"):
            with st.spinner("Dibujando conexiones complejas..."):
                from network_graph import generate_network_graph
                html_data_complex = generate_network_graph(only_complex=True)
                st.session_state['graph_html_complex'] = html_data_complex
                
        if 'graph_html_complex' in st.session_state:
            import streamlit.components.v1 as components
            components.html(st.session_state['graph_html_complex'], height=650)
    else:
        st.info("Aún no se han detectado relaciones jurídicas complejas. Recuerda usar DeepSeek para procesar o escanear documentos y detectar si modifican o derogan a otros.")
