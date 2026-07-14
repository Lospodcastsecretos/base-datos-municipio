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
    
    if st.button("Procesar Archivos", type="primary"):
        if not uploaded_files:
            st.warning("Por favor, sube al menos un archivo.")
        elif not os.getenv("GOOGLE_API_KEY"):
            st.error("⚠️ Falta configurar GOOGLE_API_KEY en el archivo .env")
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
                    status_text.text(f"Extrayendo metadatos con IA: {file.name}")
                    metadata = extract_metadata_and_summary(texto_completo)
                    
                    # 3. Generate Embedding
                    status_text.text(f"Generando vector de búsqueda (embedding): {file.name}")
                    embedding = generate_embedding(texto_completo)
                    
                    # 4. Save to DB
                    database.insert_normativa(metadata, texto_completo, file.name, embedding)
                    
                    st.success(f"✅ {file.name} procesado correctamente. (Norma: {metadata.get('numero', 'N/A')} - {metadata.get('tipo_nombre', 'N/A')})")
                    
                    # Clean up
                    os.unlink(tmp_path)
                    
                    # Rate limiting: if there's more than one file, wait to avoid hitting the 5-requests-per-minute limit
                    if len(uploaded_files) > 1 and i < len(uploaded_files) - 1:
                        status_text.text(f"Esperando 30 segundos para no exceder el límite gratuito de la API de Google...")
                        import time
                        time.sleep(30)
                        
                except Exception as e:
                    st.error(f"❌ Error al procesar {file.name}: {str(e)}")
                
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            status_text.text("¡Procesamiento finalizado!")

with tab2:
    st.header("Base de Datos de Normativas")
    if st.button("🔄 Actualizar Tabla"):
        pass # Streamlit reruns the script anyway
    
    normativas = database.get_all_normativas()
    
    if normativas:
        df = pd.DataFrame(normativas)
        # Reorder and filter columns for display
        display_df = df[['id', 'numero', 'tipo_nombre', 'titulo', 'categoria_nombre', 'fecha', 'vigente', 'resumen_ia']]
        st.dataframe(display_df, use_container_width=True)
        
        # Detail view
        st.subheader("Ver Detalle")
        selected_id = st.selectbox("Seleccionar ID de norma para ver detalles:", df['id'])
        if selected_id:
            detail = df[df['id'] == selected_id].iloc[0]
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
