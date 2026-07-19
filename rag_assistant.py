import os
import sqlite3
from dotenv import load_dotenv
import database
from ai_extractor import generate_embedding

def retrieve_context(query: str, n_results: int = 5) -> str:
    """
    Realiza una búsqueda híbrida (Semántica + Exacta) para recuperar los documentos relevantes.
    Extrae fragmentos inteligentes alrededor de las palabras clave para mejorar el RAG.
    """
    try:
        doc_ids = set()
        
        # 1. Búsqueda Semántica (ChromaDB)
        try:
            query_embedding = generate_embedding(query)
            semantic_results = database.search_normativas(query_embedding, n_results=n_results)
            if semantic_results and semantic_results['ids'] and len(semantic_results['ids'][0]) > 0:
                for doc_id_str in semantic_results['ids'][0]:
                    doc_ids.add(int(doc_id_str))
        except Exception as e:
            print(f"Error en búsqueda semántica RAG: {e}")
            
        # 2. Búsqueda Exacta (FTS5) - Optimizada para lenguaje natural
        try:
            import re
            words = re.findall(r'\b\w+\b', query.lower())
            stopwords = {'hola', 'decime', 'que', 'habla', 'sobre', 'los', 'las', 'el', 'la', 'un', 'una', 'cuales', 'son', 'reglas', 'para', 'segun', 'ordenanza', 'ley', 'decreto', 'municipal', 'como', 'cuando', 'donde', 'cual', 'cuales', 'por', 'con', 'del', 'al', 'las'}
            fts_keywords = [w for w in words if w not in stopwords and len(w) > 3]
            if fts_keywords:
                fts_query = " OR ".join(fts_keywords)
                fts_results = database.search_normativas_fts(fts_query)
                if fts_results:
                    for i, doc in enumerate(fts_results):
                        if i >= n_results: break
                        doc_ids.add(int(doc['id']))
        except Exception as e:
            print(f"Error en búsqueda FTS RAG: {e}")
            
        contexto_text = ""
        fuentes = []
        if doc_ids:
            conn = sqlite3.connect(database.DB_PATH, timeout=15)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Palabras clave de la query para buscar fragmentos (ignorando muy cortas)
            keywords = [w.lower() for w in query.split() if len(w) > 3]
            
            for doc_id in list(doc_ids)[:10]: # Máximo 10 documentos
                cursor.execute("SELECT numero, tipo_nombre, titulo, texto_completo FROM normativas WHERE id = ?", (doc_id,))
                row = cursor.fetchone()
                if row:
                    tipo = row['tipo_nombre'] or 'Documento'
                    numero = row['numero'] or 'S/N'
                    titulo = row['titulo'] or 'Sin título'
                    texto = row['texto_completo'] or ''
                    
                    fuentes.append({'id': doc_id, 'tipo': tipo, 'numero': numero, 'titulo': titulo})
                    
                    # Buscar el mejor fragmento
                    texto_lower = texto.lower()
                    match_idx = -1
                    for kw in keywords:
                        idx = texto_lower.find(kw)
                        if idx != -1:
                            match_idx = idx
                            break
                            
                    if match_idx != -1:
                        # Extraer ventana (hasta ~12,000 caracteres) alrededor de la coincidencia
                        start = max(0, match_idx - 4000)
                        end = min(len(texto), match_idx + 8000)
                        fragmento = texto[start:end]
                    else:
                        fragmento = texto[:12000]
                        
                    contexto_text += f"\n--- [FUENTE: {tipo} Nº {numero} - {titulo}] ---\n"
                    contexto_text += fragmento + "\n"
            conn.close()
            
        return contexto_text, fuentes
    except Exception as e:
        print(f"Error recuperando contexto general: {e}")
        return "", []

def answer_question_with_rag(query: str, chat_history: list, engine: str = "DeepSeek") -> tuple[str, list]:
    """
    Arma el prompt con contexto RAG y el historial, y llama a la API correspondiente.
    """
    load_dotenv()
    
    # 1. Recuperar contexto de ChromaDB
    contexto, fuentes = retrieve_context(query)
    
    if not contexto:
        contexto = "No se encontraron normativas relevantes en la base de datos para esta consulta."

    # 2. Construir los mensajes del sistema y el historial
    system_prompt = (
        "Eres un Asistente Jurídico Municipal experto. Tu tarea es responder a las preguntas "
        "legales del usuario basándote ÚNICA y EXCLUSIVAMENTE en el contexto de normativas "
        "municipales que se te provee a continuación.\n\n"
        "REGLAS ESTRICTAS:\n"
        "1. Responde en prosa, de manera clara, profesional y natural.\n"
        "2. Cita SIEMPRE explícitamente el tipo y número de norma de la que extraes la información (ej: 'Según la Ordenanza Nº 1234...').\n"
        "3. Si el texto lo indica, cita también el número de artículo o sección.\n"
        "4. Si la pregunta es sobre información existente y no está en el contexto, di que no posees información. PERO si el usuario te pide expresamente REDACTAR, CREAR o PROPONER una nueva ordenanza/norma, PUEDES hacerlo utilizando tu conocimiento general y el estilo de las normas municipales.\n"
        "5. Usa formato Markdown (negritas, viñetas) para hacer tu respuesta fácil de leer.\n\n"
        "CONTEXTO RECUPERADO DE LA BASE DE DATOS MUNICIPAL:\n"
        f"{contexto}\n"
    )

    # 3. Llamar a la API según el motor elegido
    respuesta = ""
    try:
        if "DeepSeek" in engine:
            respuesta = call_deepseek(system_prompt, chat_history, query)
        elif "OpenAI" in engine:
            respuesta = call_openai(system_prompt, chat_history, query)
        else: # Gemini
            respuesta = call_gemini(system_prompt, chat_history, query)
    except Exception as e:
        respuesta = f"❌ Error al consultar a {engine}: {str(e)}"
        
    return respuesta, fuentes

def format_history_for_openai_deepseek(system_prompt, history, new_query):
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": new_query})
    return messages

def call_openai(system_prompt, history, query):
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "⚠️ OPENAI_API_KEY no está configurada en .env"
    
    client = OpenAI(api_key=api_key)
    messages = format_history_for_openai_deepseek(system_prompt, history, query)
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.3
    )
    return response.choices[0].message.content

def call_deepseek(system_prompt, history, query):
    from openai import OpenAI
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return "⚠️ DEEPSEEK_API_KEY no está configurada en .env"
    
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    messages = format_history_for_openai_deepseek(system_prompt, history, query)
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.3
    )
    return response.choices[0].message.content

def call_gemini(system_prompt, history, query):
    import google.generativeai as genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "⚠️ GOOGLE_API_KEY no está configurada en .env"
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-flash-latest', system_instruction=system_prompt)
    
    # Format history for Gemini
    formatted_history = []
    for msg in history:
        role = 'model' if msg['role'] == 'assistant' else 'user'
        formatted_history.append({"role": role, "parts": [msg['content']]})
        
    chat = model.start_chat(history=formatted_history)
    response = chat.send_message(query)
    return response.text
