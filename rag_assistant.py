import os
import sqlite3
from dotenv import load_dotenv
import database
from ai_extractor import generate_embedding

def retrieve_context(query: str, n_results: int = 5) -> str:
    """
    Convierte la pregunta en un embedding y busca los N documentos más relevantes.
    Devuelve un string concatenado con el contexto para el LLM.
    """
    try:
        query_embedding = generate_embedding(query)
        results = database.search_normativas(query_embedding, n_results=n_results)
        
        contexto_text = ""
        if results and results['ids'] and len(results['ids'][0]) > 0:
            # Recuperar normativas completas para tener título, número y artículos
            conn = sqlite3.connect("normativas.db")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            for i, doc_id_str in enumerate(results['ids'][0]):
                doc_id = int(doc_id_str)
                cursor.execute("SELECT numero, tipo_nombre, titulo, texto_completo FROM normativas WHERE id = ?", (doc_id,))
                row = cursor.fetchone()
                if row:
                    tipo = row['tipo_nombre'] or 'Documento'
                    numero = row['numero'] or 'S/N'
                    titulo = row['titulo'] or 'Sin título'
                    texto = row['texto_completo'] or ''
                    
                    contexto_text += f"\n--- [FUENTE: {tipo} Nº {numero} - {titulo}] ---\n"
                    # Limitamos el texto a ~3000 caracteres por documento para no saturar el prompt
                    contexto_text += texto[:3000] + "\n"
            conn.close()
            
        return contexto_text
    except Exception as e:
        print(f"Error recuperando contexto: {e}")
        return ""

def answer_question_with_rag(query: str, chat_history: list, engine: str = "DeepSeek") -> str:
    """
    Arma el prompt con contexto RAG y el historial, y llama a la API correspondiente.
    """
    load_dotenv()
    
    # 1. Recuperar contexto de ChromaDB
    contexto = retrieve_context(query)
    
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
        "4. Si la pregunta no se puede responder con el contexto provisto, di claramente que no posees información sobre eso en la base de datos municipal actual. No inventes leyes ni supongas.\n"
        "5. Usa formato Markdown (negritas, viñetas) para hacer tu respuesta fácil de leer.\n\n"
        "CONTEXTO RECUPERADO DE LA BASE DE DATOS MUNICIPAL:\n"
        f"{contexto}\n"
    )

    # 3. Llamar a la API según el motor elegido
    try:
        if "DeepSeek" in engine:
            return call_deepseek(system_prompt, chat_history, query)
        elif "OpenAI" in engine:
            return call_openai(system_prompt, chat_history, query)
        else: # Gemini
            return call_gemini(system_prompt, chat_history, query)
    except Exception as e:
        return f"❌ Error al consultar a {engine}: {str(e)}"

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
