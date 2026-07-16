import os
import json
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

# Configurar API Key de DeepSeek
api_key = os.getenv("DEEPSEEK_API_KEY")

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=5, min=10, max=60))
def extract_metadata_and_summary_deepseek(texto: str) -> dict:
    """
    Uses DeepSeek API (via OpenAI standard) to extract structured metadata and generate a summary.
    """
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY no está configurada. Por favor, añádela al archivo .env")

    # Iniciar cliente compatible con OpenAI apuntando a DeepSeek
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    
    # Preparamos el esquema JSON deseado para el prompt
    schema_ejemplo = '''
    {
      "numero": "8547",
      "titulo": "Nombre oficial",
      "resumen": "Breve descripcion del texto",
      "tipo_nombre": "Ordenanza",
      "categoria_nombre": "Tránsito",
      "vigente": true,
      "fecha": "YYYY-MM-DD",
      "url_detalle": "",
      "texto_consolidado": "",
      "resumen_ia": "Resumen de exactamente 3 renglones generado por IA.",
      "referencias": ["123", "456"]
    }
    '''

    prompt_sistema = f"""
    Eres un asistente legal experto en analizar normativas municipales.
    Extrae la información del siguiente documento y devuélvela ESTRICTAMENTE en formato JSON válido, sin usar bloques de código Markdown ni texto adicional.
    El campo 'referencias' debe ser una lista con los números exactos de otras ordenanzas o decretos mencionados en el texto (ej: si menciona la Ordenanza 123 y Decreto 456, pones ["123", "456"]). Si no hay referencias, envía una lista vacía [].
    El JSON debe tener exactamente esta estructura y tipos de datos:
    {schema_ejemplo}
    """

    # Truncamos el texto para no exceder límites (DeepSeek soporta hasta 32k/64k pero limitamos a 15k para metadata)
    texto_truncado = texto[:15000]

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Documento:\n{texto_truncado}"}
            ],
            response_format={'type': 'json_object'},
            temperature=0.1
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)
        return data
        
    except Exception as e:
        # Extraer el error real si viene envuelto
        error_msg = str(e)
        print(f"Error procesando con DeepSeek: {error_msg}")
        raise e  # Lanzar el error para que Tenacity lo reintente o lo envuelva en RetryError
