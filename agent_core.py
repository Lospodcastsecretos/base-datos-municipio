import os
import sqlite3
import database
from ai_extractor import generate_embedding

# --- Tools Definitions ---

def tool_sql_query(query: str) -> str:
    """
    Ejecuta una consulta SQL SELECT en la tabla 'normativas' de la base de datos municipal.
    La tabla 'normativas' tiene las columnas: id, numero, tipo_nombre, titulo, texto_completo, fecha, vigente, resumen_ia, categoria_nombre.
    Útil para contar normativas (COUNT), filtrar por años, agrupar por categorías o verificar estados de vigencia masivos.
    NO puede ejecutar comandos INSERT, UPDATE, DELETE ni DROP.
    """
    if any(forbidden in query.upper() for forbidden in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE"]):
        return "ERROR: Solo se permiten consultas SELECT (modo lectura) por razones de seguridad."
    
    try:
        conn = sqlite3.connect(database.DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "La consulta no devolvió resultados."
            
        # Limitar resultados para no saturar el token limit
        if len(rows) > 50:
            return f"Demasiados resultados ({len(rows)}). Muestra solo los primeros 50.\n" + str([dict(r) for r in rows[:50]])
            
        return str([dict(r) for r in rows])
    except Exception as e:
        return f"ERROR ejecutando SQL: {e}"


def tool_semantic_search(query: str) -> str:
    """
    Realiza una búsqueda semántica vectorial en el contenido completo de las normativas.
    Útil para encontrar normativas que hablen sobre un tema específico (ej. "estacionamiento", "impuestos", "zonificación") aunque no usen las palabras exactas.
    Devuelve los fragmentos más relevantes de los documentos encontrados.
    """
    try:
        query_embedding = generate_embedding(query)
        semantic_results = database.search_normativas(query_embedding, n_results=5)
        
        if not semantic_results or not semantic_results['ids'] or len(semantic_results['ids'][0]) == 0:
            return "No se encontraron resultados semánticos relevantes."
            
        doc_ids = [int(doc_id) for doc_id in semantic_results['ids'][0]]
        
        contexto_text = ""
        conn = sqlite3.connect(database.DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        for doc_id in doc_ids:
            cursor.execute("SELECT numero, tipo_nombre, titulo, resumen_ia FROM normativas WHERE id = ?", (doc_id,))
            row = cursor.fetchone()
            if row:
                contexto_text += f"\n--- [ID: {doc_id} | {row['tipo_nombre']} Nº {row['numero']} - {row['titulo']}] ---\n"
                contexto_text += f"Resumen: {row['resumen_ia']}\n"
        conn.close()
        
        return contexto_text
    except Exception as e:
        return f"ERROR en búsqueda semántica: {e}"


def tool_get_document_text(doc_id: int) -> str:
    """
    Obtiene el texto completo de una normativa específica a partir de su ID.
    Útil cuando la búsqueda semántica no devuelve suficiente detalle y necesitas leer el documento completo de una ordenanza o decreto en particular.
    """
    try:
        conn = sqlite3.connect(database.DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT tipo_nombre, numero, titulo, texto_completo FROM normativas WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return f"No se encontró ningún documento con el ID {doc_id}."
            
        # Limitar a ~10000 caracteres para no desbordar el contexto si es muy grande
        texto = row['texto_completo']
        if texto and len(texto) > 10000:
            texto = texto[:10000] + "\n\n...[TEXTO TRUNCADO POR EXCESO DE LONGITUD]..."
            
        return f"Documento: {row['tipo_nombre']} Nº {row['numero']} - {row['titulo']}\n\n{texto}"
    except Exception as e:
        return f"ERROR obteniendo documento: {e}"


def tool_get_relations(doc_id: int) -> str:
    """
    Navega el grafo de relaciones jurídicas para encontrar qué normas afectan a un documento o son afectadas por él.
    Devuelve las normas que derogan, modifican o reglamentan al documento con el ID especificado.
    """
    try:
        # Aquí reutilizamos la lógica simple de SQLite para ver si hay filas en relation_edges
        conn = sqlite3.connect(database.DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Buscar donde doc_id es source (este doc afecta a otros) o target (otros afectan a este)
        cursor.execute("""
            SELECT e.relation_type, 
                   s.tipo_nombre as s_tipo, s.numero as s_num, s.titulo as s_titulo,
                   t.tipo_nombre as t_tipo, t.numero as t_num, t.titulo as t_titulo
            FROM relation_edges e
            JOIN normativas s ON e.source_id = s.id
            JOIN normativas t ON e.target_id = t.id
            WHERE e.source_id = ? OR e.target_id = ?
        """, (doc_id, doc_id))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return f"El documento ID {doc_id} no tiene relaciones jurídicas registradas (no deroga ni es derogado por otra norma en el sistema)."
            
        result = f"Relaciones jurídicas para el ID {doc_id}:\n"
        for r in rows:
            result += f"- {r['s_tipo']} Nº {r['s_num']} ({r['relation_type']}) a {r['t_tipo']} Nº {r['t_num']}\n"
            
        return result
    except Exception as e:
        return f"ERROR buscando relaciones: {e}"

# Lista de todas las herramientas disponibles para el Agente
agent_tools = [tool_sql_query, tool_semantic_search, tool_get_document_text, tool_get_relations]

# --- Agent Invocation ---

def run_agent_gemini(query: str, history: list, callback=None) -> tuple[str, list]:
    """
    Ejecuta el Agente Autónomo usando Google Gemini y Function Calling automático.
    El callback se usa para notificar a la UI (st.info) qué herramientas está usando el agente.
    Retorna (Respuesta_Final, fuentes_utilizadas)
    """
    import google.generativeai as genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "⚠️ GOOGLE_API_KEY no está configurada en .env", []
        
    genai.configure(api_key=api_key)
    
    system_instruction = (
        "Eres un Agente Autónomo Jurídico de la Municipalidad.\n"
        "Tienes acceso a un conjunto de herramientas (tools) para investigar la base de datos municipal.\n"
        "REGLAS ESTRICTAS:\n"
        "1. Para responder la pregunta del usuario, debes decidir inteligentemente qué herramientas usar.\n"
        "2. Si la pregunta requiere contar, agrupar o filtrar, usa SIEMPRE la herramienta SQL.\n"
        "3. Si la pregunta es sobre el contenido o significado de algo, usa la herramienta de búsqueda semántica.\n"
        "4. Si encuentras una norma relevante y necesitas ver todo su texto, usa get_document_text.\n"
        "5. Analiza la respuesta de las herramientas y combínala para dar una respuesta final clara y completa al usuario.\n"
        "6. DEBES citar el tipo y número de las normas que encuentres (ej: Ordenanza Nº 123).\n"
    )
    
    # Enable automatic function calling in Gemini
    model = genai.GenerativeModel(
        model_name='gemini-1.5-pro',
        tools=agent_tools,
        system_instruction=system_instruction
    )
    
    # Format history
    formatted_history = []
    for msg in history:
        role = 'model' if msg['role'] == 'assistant' else 'user'
        formatted_history.append({"role": role, "parts": [msg['content']]})
        
    chat = model.start_chat(
        history=formatted_history, 
        enable_automatic_function_calling=True
    )
    
    if callback:
        callback("💭 El agente está analizando tu petición y consultando herramientas (puede tardar unos segundos)...")
        
    # Send message
    response = chat.send_message(query)
    
    # Optionally, we could inspect chat.history to see which functions were called
    # For now, Gemini's enable_automatic_function_calling handles the loop under the hood beautifully!
    
    return response.text, [{"tipo": "Agente", "numero": "Autónomo", "titulo": "Búsqueda Dinámica", "id": 0}]


def run_agent_openai(query: str, history: list, callback=None, engine="OpenAI") -> tuple[str, list]:
    """
    Ejecuta el Agente Autónomo usando OpenAI o DeepSeek mediante Function Calling manual (bucle ReAct).
    """
    from openai import OpenAI
    import json
    
    if "DeepSeek" in engine:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return "⚠️ DEEPSEEK_API_KEY no está configurada en .env", []
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        model_name = "deepseek-chat"
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return "⚠️ OPENAI_API_KEY no está configurada en .env", []
        client = OpenAI(api_key=api_key)
        model_name = "gpt-4o-mini"
    
    system_instruction = (
        "Eres un Agente Autónomo Jurídico de la Municipalidad.\n"
        "Tienes acceso a un conjunto de herramientas (tools) para investigar la base de datos municipal.\n"
        "REGLAS ESTRICTAS:\n"
        "1. Para responder la pregunta del usuario, debes decidir inteligentemente qué herramientas usar.\n"
        "2. Si la pregunta requiere contar, agrupar o filtrar, usa SIEMPRE la herramienta SQL.\n"
        "3. Si la pregunta es sobre el contenido o significado de algo, usa la herramienta de búsqueda semántica.\n"
        "4. Si encuentras una norma relevante y necesitas ver todo su texto, usa get_document_text.\n"
        "5. Analiza la respuesta de las herramientas y combínala para dar una respuesta final clara y completa al usuario.\n"
        "6. DEBES citar el tipo y número de las normas que encuentres (ej: Ordenanza Nº 123).\n"
    )
    
    messages = [{"role": "system", "content": system_instruction}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": query})
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "tool_sql_query",
                "description": "Ejecuta una consulta SQL SELECT en la tabla 'normativas'. Columnas: id, numero, tipo_nombre, titulo, texto_completo, fecha, vigente, resumen_ia, categoria_nombre.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Consulta SQL SELECT completa y válida"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "tool_semantic_search",
                "description": "Realiza una búsqueda semántica vectorial en el contenido de las normativas.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Términos de búsqueda semántica"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "tool_get_document_text",
                "description": "Obtiene el texto completo de una normativa específica a partir de su ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "integer", "description": "ID numérico de la normativa"}
                    },
                    "required": ["doc_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "tool_get_relations",
                "description": "Navega el grafo de relaciones jurídicas para encontrar qué normas afectan a un documento o son afectadas por él.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "integer", "description": "ID numérico de la normativa"}
                    },
                    "required": ["doc_id"]
                }
            }
        }
    ]
    
    available_functions = {
        "tool_sql_query": tool_sql_query,
        "tool_semantic_search": tool_semantic_search,
        "tool_get_document_text": tool_get_document_text,
        "tool_get_relations": tool_get_relations,
    }

    if callback:
        callback(f"💭 El agente ({engine}) está analizando tu petición y consultando herramientas...")
        
    for iteration in range(6): # Max 6 tool iterations
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls
            
            if tool_calls:
                messages.append(response_message)
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_to_call = available_functions.get(function_name)
                    if not function_to_call:
                        continue
                        
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                        function_response = function_to_call(**function_args)
                    except Exception as e:
                        function_response = f"Error: {e}"
                        
                    messages.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": str(function_response),
                        }
                    )
            else:
                return response_message.content, [{"tipo": "Agente", "numero": f"Autónomo ({engine})", "titulo": "Búsqueda Dinámica", "id": 0}]
        except Exception as e:
            return f"❌ Error en el ciclo del Agente: {str(e)}", []
            
    return "⚠️ El agente alcanzó el límite máximo de iteraciones sin llegar a una respuesta final.", []
