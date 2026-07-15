import os
import pdfplumber
import docx

def process_document(file_path: str) -> str:
    """
    Extracts text from a given document file (PDF, DOCX).
    Returns the extracted text as a string.
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == '.pdf':
        return _process_pdf(file_path)
    elif ext == '.docx':
        return _process_docx(file_path)
    elif ext == '.doc':
        # For .doc we can try to warn or use a specific library later if needed
        # Often win32com is used, but for now we raise NotImplementedError or return a stub
        return _process_doc(file_path)
    else:
        raise ValueError(f"Formato no soportado: {ext}")

def _process_pdf(file_path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"Error leyendo PDF {file_path}: {e}")
        
    text = text.strip()
    
    # Si el texto es muy corto o vacío, es probable que sea un documento escaneado/imagen
    if len(text) < 50:
        print(f"[{file_path}] Poco texto detectado. Iniciando OCR con Gemini...")
        from ai_extractor import transcribe_pdf_with_gemini
        ocr_text = transcribe_pdf_with_gemini(file_path)
        if ocr_text:
            return "[NOTA_SISTEMA: Documento escaneado. Texto transcrito mediante OCR por IA]\n\n" + ocr_text.strip()
            
    return text

def _process_docx(file_path: str) -> str:
    text = ""
    try:
        doc = docx.Document(file_path)
        for para in doc.paragraphs:
            text += para.text + "\n"
    except Exception as e:
        print(f"Error leyendo DOCX {file_path}: {e}")
    return text.strip()

def _process_doc(file_path: str) -> str:
    # Requires Microsoft Word installed on Windows to use win32com, or external tools
    # For now, we will return a placeholder or attempt a basic extraction if antiword is installed.
    # To keep it simple in pure python, we might just warn the user.
    raise NotImplementedError("El soporte para archivos .doc requiere librerías adicionales. Por favor, convierte el archivo a .docx o .pdf.")
