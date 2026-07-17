import sqlite3
import re
import json

def backfill():
    conn = sqlite3.connect('normativas.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, texto_completo, referencias FROM normativas")
    rows = cursor.fetchall()
    
    updated = 0
    for row in rows:
        db_id, texto, ref = row
        if not texto: continue
        
        # Si ya tiene referencias por DeepSeek y no esta vacio, lo dejamos
        if ref and ref != '[]' and ref != 'None':
            continue
            
        # Buscar patrones "Ordenanza N° 854", "Decreto 123", etc
        # Regex simple para encontrar numeros cerca de la palabra Ordenanza o Decreto
        matches = re.findall(r'(?i)(?:ordenanza|decreto|resoluci[oó]n|ley)\s*(?:n[°oº]?\s*|numero\s*|num\s*)?(\d+)', texto)
        
        # Limpiar duplicados y vacios
        refs_list = list(set([m for m in matches if m]))
        
        # Remover el numero de la propia ordenanza si se menciona a si misma
        # (necesitamos el numero de esta ordenanza para no linkearse a si misma, pero es complejo aqui sin otra query, 
        # igual pyvis ignora si se conecta a si misma usualmente, pero es mejor limpiar)
        
        if refs_list:
            cursor.execute("UPDATE normativas SET referencias = ? WHERE id = ?", (json.dumps(refs_list), db_id))
            updated += 1
            
    conn.commit()
    conn.close()
    print(f"Updated {updated} records using Regex fallback.")

if __name__ == '__main__':
    backfill()
