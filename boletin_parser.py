import re

def parse_boletin_markdown(text: str) -> list[str]:
    """
    Recibe el texto de un Boletín Oficial en formato Markdown.
    Lo divide en fragmentos, donde cada fragmento se considera una normativa individual.
    Devuelve una lista de strings (el texto completo de cada normativa extraída).
    """
    
    # 1. Intentar dividir por encabezados principales o secundarios (# o ##)
    # Expresión regular para encontrar encabezados que probablemente inicien una normativa.
    # Buscamos cosas como "# DECRETO", "## ORDENANZA", "# Resolucion 123", etc.
    # También podemos simplemente dividir por cualquier encabezado de nivel 1 o 2
    # que tenga ciertas palabras clave, o de manera genérica dividir por cualquier título 
    # y luego filtrar los fragmentos.
    
    # Patrón: un inicio de línea, seguido de 1 a 3 '#', un espacio, y luego el título.
    # Usamos lookahead (?=...) para no consumir el delimitador en el split, o split directo 
    # y luego reconstruimos.
    
    lines = text.split('\n')
    
    normas = []
    current_norma = []
    
    # Palabras clave comunes que inician una norma legal en Argentina/Latam
    keywords = ['decreto', 'ordenanza', 'resolucion', 'ley', 'disposicion', 'acuerdo']
    
    for line in lines:
        # Detectar si la línea es un encabezado
        match = re.match(r'^(#{1,3})\s+(.*)', line.strip())
        is_header = False
        
        if match:
            header_text = match.group(2).lower()
            # Si el encabezado contiene alguna de las palabras clave, iniciamos nueva norma
            if any(kw in header_text for kw in keywords):
                is_header = True
                
        if is_header:
            # Guardamos la norma anterior si tiene contenido sustancial
            texto_norma = "\n".join(current_norma).strip()
            if len(texto_norma) > 100: # Ignorar fragmentos muy cortos
                normas.append(texto_norma)
            # Empezamos una nueva norma con este encabezado
            current_norma = [line]
        else:
            current_norma.append(line)
            
    # Agregar la última norma
    texto_norma = "\n".join(current_norma).strip()
    if len(texto_norma) > 100:
        # Check if the last collected text actually looks like a norm or if it's just the start of the document
        # If it's the very first chunk and we never found a header, it will just append it.
        normas.append(texto_norma)
        
    # Si la lista de normas es muy corta (ej. 1), significa que no encontró separadores claros.
    # En ese caso, podríamos intentar otra heurística (como separar por "VISTO:" o "EL INTENDENTE..."),
    # pero por ahora, devolver lo que tenemos asumiendo formato Markdown.
    
    return normas
