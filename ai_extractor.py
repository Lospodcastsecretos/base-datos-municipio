import os
import google.generativeai as genai
from pydantic import BaseModel, Field
import json
from dotenv import load_dotenv

load_dotenv()

# Configurar API Key de Gemini
# El usuario deberá poner su GOOGLE_API_KEY en un archivo .env o en las variables de entorno
api_key = os.getenv("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

class NormativaMetadata(BaseModel):
    numero: str = Field(description="El número de la norma (ej. '8547'). Si no se encuentra, dejar vacío.")
    titulo: str = Field(description="El nombre oficial completo de la norma.")
    resumen: str = Field(description="La breve descripción que provee la municipalidad en el texto, si existe.")
    tipo_nombre: str = Field(description="Si es 'Ordenanza', 'Decreto', 'Resolución', etc.")
    categoria_nombre: str = Field(description="El tema (ej. 'Tránsito', 'Hacienda', 'Obras Públicas'). Si no está explícito, inferirlo.")
    vigente: bool = Field(description="Si la norma sigue activa o si fue derogada explícitamente en el texto.")
    fecha: str = Field(description="Fecha de promulgación en formato YYYY-MM-DD. Si no se sabe exacto, estimar o dejar vacío.")
    url_detalle: str = Field(description="El link original al sistema viejo de la municipalidad, si está presente en el documento.")
    texto_consolidado: str = Field(description="El texto de la norma con modificaciones aplicadas, si se menciona. Sino, dejar igual al original o vacío.")
    resumen_ia: str = Field(description="Un resumen de exactamente 3 renglones generado por la Inteligencia Artificial explicando de qué trata.")
    relaciones_juridicas: list = Field(description="Lista de objetos describiendo la acción sobre otras normas (modifica, deroga, etc).")
    articulos: list = Field(description="Lista de objetos con número y texto de cada artículo de la norma.")

from tenacity import retry, stop_after_attempt, wait_fixed

@retry(stop=stop_after_attempt(5), wait=wait_fixed(65))
def extract_metadata_and_summary(texto: str) -> dict:
    """
    Uses Gemini to extract structured metadata and generate a summary from the document text.
    """
    load_dotenv()
    current_key = os.getenv("GOOGLE_API_KEY")
    if not current_key:
        raise ValueError("GOOGLE_API_KEY no está configurada. Por favor, añádela al archivo .env")
    genai.configure(api_key=current_key)

    # Use the latest available Flash model to avoid version deprecation errors
    model = genai.GenerativeModel('gemini-flash-latest')
    
    prompt = f"""
    Eres un asistente legal experto en analizar normativas municipales.
    A continuación, te proveeré el texto de un documento oficial de una municipalidad.
    Tu tarea es extraer la información clave y devolverla ESTRICTAMENTE en formato JSON, siguiendo este esquema:

    {{
      "numero": "string",
      "titulo": "string",
      "resumen": "string",
      "tipo_nombre": "string",
      "categoria_nombre": "string",
      "vigente": boolean,
      "fecha": "YYYY-MM-DD",
      "url_detalle": "string",
      "texto_consolidado": "string",
      "resumen_ia": "string (resumen de exactamente 3 renglones)",
      "referencias": ["123", "456"],
      "relaciones_juridicas": [
        {{
          "norma_destino": "123",
          "accion": "modifica",
          "detalle": "modifica el art 3"
        }}
      ],
      "articulos": [
        {{
          "numero": "1",
          "texto": "Modificase el articulo 3 de la ordenanza 123..."
        }},
        {{
          "numero": "2",
          "texto": "Comuniquese, publiquese y archivese."
        }}
      ]
    }}

    Texto del documento:
    {texto[:10000]} # Limitamos a los primeros 10k caracteres para evitar exceder límites si es muy largo, asumiendo que los metadatos están al principio.
    """

    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.1,
        )
    )
    
    try:
        data = json.loads(response.text)
        return data
    except Exception as e:
        print(f"Error parseando JSON de Gemini: {e}")
        print("Respuesta cruda:", response.text)
        # Fallback values
        return {
            "numero": "", "titulo": "Error en extracción", "resumen": "",
            "tipo_nombre": "", "categoria_nombre": "", "vigente": True,
            "fecha": "", "url_detalle": "", "texto_consolidado": "", "resumen_ia": "No se pudo generar el resumen."
        }

# Inicializar el modelo local de embeddings de manera diferida (lazy loading)
_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        # Usamos un modelo multilingüe excelente para español, que se descarga automáticamente a la PC.
        _embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    return _embedding_model

def generate_embedding(texto: str) -> list[float]:
    """
    Generates an embedding vector for the given text using a LOCAL model.
    100% free, no API keys, no quotas.
    """
    model = get_embedding_model()
    # Generar el vector (truncamos a 10000 caracteres como precaución, aunque los modelos locales cortan automáticamente en ~512 tokens)
    embedding = model.encode(texto[:10000]).tolist()
    return embedding
