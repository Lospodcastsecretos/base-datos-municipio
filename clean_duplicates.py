import sqlite3
import chromadb
import os

DB_PATH = "normativas.db"
CHROMA_PATH = "./chroma_db"

def clean_duplicates():
    print("Iniciando depuración de duplicados exactos...")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. Buscar grupos duplicados por numero y tipo (excluyendo los que sabemos que son falsos positivos de ejemplo o sin numero)
    cursor.execute('''
        SELECT numero, tipo_nombre, COUNT(*) as c 
        FROM normativas 
        WHERE numero NOT IN ('8547', 'S/N', 'None', '', 'unico', 'Unico') 
          AND numero IS NOT NULL
          AND tipo_nombre IS NOT NULL
        GROUP BY numero, tipo_nombre 
        HAVING c > 1
    ''')
    
    duplicate_groups = cursor.fetchall()
    total_groups = len(duplicate_groups)
    print(f"Se encontraron {total_groups} grupos de normativas duplicadas.")
    
    # Conectarse a ChromaDB para borrar los vectores correspondientes
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = chroma_client.get_collection(name="normativas_vectores")
    except Exception as e:
        print(f"Error al conectar con ChromaDB: {e}")
        collection = None
        
    deleted_count = 0
    
    for i, group in enumerate(duplicate_groups):
        num = group['numero']
        tipo = group['tipo_nombre']
        
        # Obtener todos los registros para este grupo
        cursor.execute('''
            SELECT id, titulo, fecha, archivo_origen, texto_completo 
            FROM normativas 
            WHERE numero = ? AND tipo_nombre = ?
        ''', (num, tipo))
        records = [dict(row) for row in cursor.fetchall()]
        
        # Evaluar cada registro para ver cuál es el "mejor" a conservar
        scored_records = []
        for r in records:
            r_id = r['id']
            # Puntuación por tener artículos estructurados
            cursor.execute("SELECT COUNT(*) FROM articulos WHERE normativa_id = ?", (r_id,))
            has_articles = cursor.fetchone()[0] > 0
            
            # Puntuación básica: prioriza tener artículos, texto más largo y fecha no vacía
            score = 0
            if has_articles:
                score += 1000
            if r['fecha'] and r['fecha'] != '2000-01-01':
                score += 100
            score += len(r['texto_completo']) // 100
            
            scored_records.append((score, r))
            
        # Ordenar por puntuación descendente (el mejor primero)
        scored_records.sort(key=lambda x: x[0], reverse=True)
        
        # Conservar el primero, borrar el resto
        kept_record = scored_records[0][1]
        to_delete = scored_records[1:]
        
        print(f"[{i+1}/{total_groups}] {tipo} Nº {num}: Conservando ID {kept_record['id']} ({kept_record['archivo_origen']})")
        
        for score, r in to_delete:
            del_id = r['id']
            print(f"  -> Eliminando duplicado ID {del_id} ({r['archivo_origen']})")
            
            # 1. Borrar de SQLite normativas
            cursor.execute("DELETE FROM normativas WHERE id = ?", (del_id,))
            
            # 2. Borrar de SQLite articulos
            cursor.execute("DELETE FROM articulos WHERE normativa_id = ?", (del_id,))
            
            # 3. Borrar de SQLite FTS5
            cursor.execute("DELETE FROM normativas_fts WHERE rowid = ?", (del_id,))
            
            # 4. Borrar de ChromaDB
            if collection:
                try:
                    collection.delete(ids=[str(del_id)])
                except Exception as e:
                    print(f"     * Error al borrar vector de ID {del_id}: {e}")
                    
            deleted_count += 1
            
    conn.commit()
    conn.close()
    print(f"\n¡Depuración completada! Se eliminaron {deleted_count} registros duplicados de forma segura.")

if __name__ == "__main__":
    clean_duplicates()
