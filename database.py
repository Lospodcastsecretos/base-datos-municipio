import sqlite3
import chromadb
import json
import os

DB_PATH = "normativas.db"
CHROMA_PATH = "./chroma_db"

def init_db():
    """Initializes SQLite database and ChromaDB collection."""
    # SQLite
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS normativas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT,
            titulo TEXT,
            resumen TEXT,
            tipo_nombre TEXT,
            categoria_nombre TEXT,
            vigente BOOLEAN,
            fecha TEXT,
            url_detalle TEXT,
            texto_completo TEXT,
            texto_consolidado TEXT,
            resumen_ia TEXT,
            archivo_origen TEXT,
            referencias TEXT,
            relaciones_juridicas TEXT
        )
    ''')
    
    # Auto-migration: check if 'referencias' or 'relaciones_juridicas' column exists, if not, add it
    cursor.execute("PRAGMA table_info(normativas)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'referencias' not in columns:
        cursor.execute("ALTER TABLE normativas ADD COLUMN referencias TEXT")
    if 'relaciones_juridicas' not in columns:
        cursor.execute("ALTER TABLE normativas ADD COLUMN relaciones_juridicas TEXT")
        
    # Crear tabla de articulos si no existe
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articulos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normativa_id INTEGER,
            numero TEXT,
            texto TEXT,
            version_numero INTEGER DEFAULT 1,
            fecha_desde TEXT,
            fecha_hasta TEXT,
            fuente_normativa_id INTEGER,
            FOREIGN KEY(normativa_id) REFERENCES normativas(id)
        )
    ''')
    
    # Auto-migration: check if versioning columns exist in articulos
    cursor.execute("PRAGMA table_info(articulos)")
    art_columns = [col[1] for col in cursor.fetchall()]
    if 'version_numero' not in art_columns:
        cursor.execute("ALTER TABLE articulos ADD COLUMN version_numero INTEGER DEFAULT 1")
    if 'fecha_desde' not in art_columns:
        cursor.execute("ALTER TABLE articulos ADD COLUMN fecha_desde TEXT")
    if 'fecha_hasta' not in art_columns:
        cursor.execute("ALTER TABLE articulos ADD COLUMN fecha_hasta TEXT")
    if 'fuente_normativa_id' not in art_columns:
        cursor.execute("ALTER TABLE articulos ADD COLUMN fuente_normativa_id INTEGER")
        
    # Migrar registros viejos de articulos para asignarles fecha_desde y fuente_normativa_id por defecto
    cursor.execute('''
        UPDATE articulos 
        SET fecha_desde = (SELECT COALESCE(fecha, '2000-01-01') FROM normativas WHERE normativas.id = articulos.normativa_id),
            fuente_normativa_id = normativa_id
        WHERE fecha_desde IS NULL OR fuente_normativa_id IS NULL
    ''')
    
    # Crear tabla virtual FTS5 para busqueda de texto completo
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS normativas_fts USING fts5(
            normativa_id,
            numero,
            titulo,
            texto_completo
        )
    ''')
    
    # Retro-indexar si la tabla FTS5 esta vacia pero hay normativas
    cursor.execute("SELECT COUNT(*) FROM normativas_fts")
    if cursor.fetchone()[0] == 0:
        cursor.execute("SELECT COUNT(*) FROM normativas")
        if cursor.fetchone()[0] > 0:
            cursor.execute('''
                INSERT INTO normativas_fts (rowid, normativa_id, numero, titulo, texto_completo)
                SELECT id, id, numero, titulo, texto_completo FROM normativas
            ''')
        
    conn.commit()
    conn.close()

    # ChromaDB
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = chroma_client.get_or_create_collection(name="normativas_vectores")
    return collection

def insert_normativa(metadata: dict, texto_completo: str, archivo_origen: str, embedding: list[float]):
    """Inserts a new document and its metadata into SQLite and ChromaDB."""
    import json
    # Insert in SQLite
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Asegurar que referencias sea un string JSON si viene como lista
    refs = metadata.get('referencias', [])
    if isinstance(refs, list):
        refs_str = json.dumps(refs)
    else:
        refs_str = str(refs)
        
    # Check if 'relaciones_juridicas' is present
    rels_str = '[]'
    rels = metadata.get('relaciones_juridicas', [])
    if isinstance(rels, list):
        rels_str = json.dumps(rels)
    else:
        rels_str = str(rels)
        
    cursor.execute('''
        INSERT INTO normativas (numero, titulo, resumen, tipo_nombre, categoria_nombre, vigente, fecha, url_detalle, texto_completo, texto_consolidado, resumen_ia, archivo_origen, referencias, relaciones_juridicas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        metadata.get('numero', ''),
        metadata.get('titulo', ''),
        metadata.get('resumen', ''),
        metadata.get('tipo_nombre', ''),
        metadata.get('categoria_nombre', ''),
        metadata.get('vigente', True),
        metadata.get('fecha', ''),
        metadata.get('url_detalle', ''),
        texto_completo,
        metadata.get('texto_consolidado', ''),
        metadata.get('resumen_ia', ''),
        archivo_origen,
        refs_str,
        rels_str
    ))
    normativa_id = cursor.lastrowid
    
    # Insertar articulos si existen
    articulos = metadata.get('articulos', [])
    fecha_norma = metadata.get('fecha', '') or '2000-01-01'
    if isinstance(articulos, list):
        for art in articulos:
            num_art = art.get('numero', '')
            txt_art = art.get('texto', '')
            if txt_art:
                cursor.execute('''
                    INSERT INTO articulos (normativa_id, numero, texto, version_numero, fecha_desde, fuente_normativa_id)
                    VALUES (?, ?, ?, 1, ?, ?)
                ''', (normativa_id, num_art, txt_art, fecha_norma, normativa_id))
    
    # Insertar en FTS5
    cursor.execute('''
        INSERT INTO normativas_fts (rowid, normativa_id, numero, titulo, texto_completo)
        VALUES (?, ?, ?, ?, ?)
    ''', (normativa_id, normativa_id, metadata.get('numero', ''), metadata.get('titulo', ''), texto_completo))
    
    conn.commit()
    conn.close()

    # Insert in ChromaDB
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = chroma_client.get_or_create_collection(name="normativas_vectores")
    
    collection.add(
        embeddings=[embedding],
        documents=[texto_completo], # Almacenamos el texto para que lo devuelva al buscar
        metadatas=[{"db_id": normativa_id, "numero": metadata.get('numero', ''), "titulo": metadata.get('titulo', '')}],
        ids=[str(normativa_id)]
    )

def search_normativas(query_embedding: list[float], n_results: int = 5):
    """Searches for similar documents in ChromaDB using a query embedding."""
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = chroma_client.get_collection(name="normativas_vectores")
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results
    )
    return results

def get_all_normativas():
    """Retrieves all documents from SQLite."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM normativas')
    rows = cursor.fetchall()
    
    columns = [description[0] for description in cursor.description]
    result = [dict(zip(columns, row)) for row in rows]
    
    conn.close()
    return result

def update_normativa(db_id: int, updated_data: dict):
    """Updates a document's metadata in SQLite."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Construir query dinámica para actualizar solo los campos proporcionados
    fields = []
    values = []
    
    for key in ['numero', 'titulo', 'tipo_nombre', 'categoria_nombre', 'vigente', 'fecha', 'resumen_ia', 'referencias', 'relaciones_juridicas']:
        if key in updated_data:
            fields.append(f"{key} = ?")
            values.append(updated_data[key])
            
    if not fields:
        return
        
    values.append(db_id)
    cursor.execute(query, tuple(values))
    
    # Sincronizar FTS5
    fts_fields = []
    fts_values = []
    for key in ['numero', 'titulo', 'texto_completo']:
        if key in updated_data:
            fts_fields.append(f"{key} = ?")
            fts_values.append(updated_data[key])
    if fts_fields:
        fts_values.append(db_id)
        cursor.execute(f"UPDATE normativas_fts SET {', '.join(fts_fields)} WHERE rowid = ?", tuple(fts_values))
        
    conn.commit()
    conn.close()
    
    # Optionally update metadata in ChromaDB if needed
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = chroma_client.get_collection(name="normativas_vectores")
        collection.update(
            ids=[str(db_id)],
            metadatas=[{"db_id": db_id, "numero": updated_data.get('numero', ''), "titulo": updated_data.get('titulo', '')}]
        )
    except Exception as e:
        print(f"Error updating ChromaDB metadata for {db_id}: {e}")

def delete_normativa(id_normativa: int):
    """Deletes a document from SQLite and ChromaDB by ID."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM normativas WHERE id = ?", (id_normativa,))
    cursor.execute("DELETE FROM articulos WHERE normativa_id = ?", (id_normativa,))
    cursor.execute("DELETE FROM normativas_fts WHERE rowid = ?", (id_normativa,))
    conn.commit()
    conn.close()
    
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = chroma_client.get_or_create_collection(name="normativas_vectores")
        collection.delete(ids=[str(id_normativa)])
    except Exception as e:
        print(f"Error borrando de ChromaDB: {e}")

def get_articulos_por_norma(normativa_id: int, fecha: str = None) -> list[dict]:
    """Retrieves all articles for a given document at a specific date, indicating if they are active or derogated."""
    if not fecha:
        import datetime
        fecha = datetime.date.today().strftime('%Y-%m-%d')
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Esta query obtiene la version del articulo que corresponde a la fecha seleccionada
    # e indica con 'es_vigente' si estaba activo (1) o ya habia sido derogado (0)
    cursor.execute('''
        SELECT a.*, 
               (CASE 
                    WHEN (a.fecha_hasta IS NULL OR a.fecha_hasta = '' OR a.fecha_hasta > ?) THEN 1 
                    ELSE 0 
                END) as es_vigente
        FROM articulos a
        WHERE a.normativa_id = ?
          AND (a.fecha_desde <= ? OR a.fecha_desde IS NULL OR a.fecha_desde = '')
          AND a.version_numero = (
              SELECT MAX(a2.version_numero) 
              FROM articulos a2 
              WHERE a2.normativa_id = a.normativa_id 
                AND a2.numero = a.numero 
                AND (a2.fecha_desde <= ? OR a2.fecha_desde IS NULL OR a2.fecha_desde = '')
          )
        ORDER BY CAST(a.numero AS INTEGER), a.numero ASC
    ''', (fecha, normativa_id, fecha, fecha))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_historial_articulo(normativa_id: int, numero_articulo: str) -> list[dict]:
    """Retrieves all versions of a specific article for history tracking."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.*, n.numero as fuente_norma_numero, n.tipo_nombre as fuente_norma_tipo
        FROM articulos a
        LEFT JOIN normativas n ON a.fuente_normativa_id = n.id
        WHERE a.normativa_id = ? AND a.numero = ?
        ORDER BY a.version_numero ASC
    ''', (normativa_id, numero_articulo))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def search_normativas_fts(query_text: str) -> list[dict]:
    """Searches using SQLite FTS5 MATCH syntax with a fallback to LIKE on error."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        # FTS5 MATCH ordenado por relevancia (rank)
        cursor.execute('''
            SELECT n.*, fts.rank 
            FROM normativas n
            JOIN normativas_fts fts ON n.id = fts.rowid
            WHERE normativas_fts MATCH ?
            ORDER BY fts.rank ASC
        ''', (query_text,))
        rows = cursor.fetchall()
    except Exception as e:
        # Fallback a LIKE clásico si falla la sintaxis de MATCH
        print(f"FTS5 falló (usando fallback LIKE): {e}")
        like_query = f"%{query_text}%"
        cursor.execute('''
            SELECT *, 0.0 as rank FROM normativas 
            WHERE numero LIKE ? OR titulo LIKE ? OR texto_completo LIKE ?
        ''', (like_query, like_query, like_query))
        rows = cursor.fetchall()
        
    conn.close()
    return [dict(row) for row in rows]

def reset_database():
    """Wipes all data from SQLite and ChromaDB."""
    # Delete all records from SQLite
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM normativas')
    # Resetea el contador de ID (AUTOINCREMENT) para que vuelva a empezar desde 1
    cursor.execute("DELETE FROM sqlite_sequence WHERE name='normativas'")
    conn.commit()
    conn.close()
    
    # Wipe ChromaDB collection
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        chroma_client.delete_collection(name="normativas_vectores")
        # Recreate an empty collection
        chroma_client.get_or_create_collection(name="normativas_vectores")
    except Exception as e:
        print(f"Error resetting ChromaDB: {e}")
