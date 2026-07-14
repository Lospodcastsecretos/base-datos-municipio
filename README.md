# Sistema de Gestión de Normativas Municipales

Aplicación local desarrollada en Python y Streamlit para la digitalización, extracción de metadatos y búsqueda semántica de normativas municipales (Ordenanzas, Decretos, Resoluciones). 

El sistema utiliza la inteligencia artificial de **Google Gemini** para leer documentos en formatos PDF o DOCX, extraer información clave estructurada, generar resúmenes automáticos y convertirlos en vectores matemáticos para realizar búsquedas inteligentes (RAG).

## Características principales

- **Extracción de Texto:** Soporte para archivos `.pdf` y `.docx`.
- **Parseo Inteligente con LLMs:** Identificación automática de número de norma, título, categoría, estado de vigencia y fechas.
- **Búsqueda Semántica:** Base de datos vectorial con `ChromaDB` para buscar por significado y contexto usando lenguaje natural.
- **Base de Datos Relacional:** Almacenamiento local en `SQLite` para rápida visualización y exploración.
- **Tolerancia a Fallos:** Reintentos automáticos para manejar límites de cuota de APIs gratuitas.

## Instalación

1. Clona este repositorio o descarga los archivos.
2. Crea un entorno virtual e instala las dependencias (puedes ejecutar el paso a paso del archivo `run_app.bat` para automatizarlo en Windows).
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install streamlit pandas sqlite3 pdfplumber python-docx google-generativeai chromadb pydantic python-dotenv tenacity
   ```
3. Crea un archivo `.env` en la raíz del proyecto y añade tu clave de Google API:
   ```env
   GOOGLE_API_KEY=tu_clave_aqui
   ```

## Uso

Para iniciar la interfaz gráfica, simplemente ejecuta:
```bash
run_app.bat
```
O directamente desde la terminal:
```bash
streamlit run app.py
```
