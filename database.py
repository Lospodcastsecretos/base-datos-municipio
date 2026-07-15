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
            archivo_origen TEXT
        )
    ''')
    conn.commit()
    conn.close()

    # ChromaDB
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = chroma_client.get_or_create_collection(name="normativas_vectores")
    return collection

def insert_normativa(metadata: dict, texto_completo: str, archivo_origen: str, embedding: list[float]):
    """Inserts a new document and its metadata into SQLite and ChromaDB."""
    # Insert in SQLite
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO normativas (
            numero, titulo, resumen, tipo_nombre, categoria_nombre, 
            vigente, fecha, url_detalle, texto_completo, 
            texto_consolidado, resumen_ia, archivo_origen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        archivo_origen
    ))
    db_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Insert in ChromaDB
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = chroma_client.get_or_create_collection(name="normativas_vectores")
    
    collection.add(
        embeddings=[embedding],
        documents=[texto_completo], # Almacenamos el texto para que lo devuelva al buscar
        metadatas=[{"db_id": db_id, "numero": metadata.get('numero', ''), "titulo": metadata.get('titulo', '')}],
        ids=[str(db_id)]
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
    cursor.execute('''
        UPDATE normativas 
        SET numero = ?, titulo = ?, tipo_nombre = ?, categoria_nombre = ?, vigente = ?, fecha = ?, resumen_ia = ?
        WHERE id = ?
    ''', (
        updated_data.get('numero', ''),
        updated_data.get('titulo', ''),
        updated_data.get('tipo_nombre', ''),
        updated_data.get('categoria_nombre', ''),
        updated_data.get('vigente', True),
        updated_data.get('fecha', ''),
        updated_data.get('resumen_ia', ''),
        db_id
    ))
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

def delete_normativa(db_id: int):
    """Deletes a document from both SQLite and ChromaDB."""
    # Delete from SQLite
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM normativas WHERE id = ?', (db_id,))
    conn.commit()
    conn.close()
    
    # Delete from ChromaDB
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = chroma_client.get_collection(name="normativas_vectores")
        collection.delete(ids=[str(db_id)])
    except Exception as e:
        print(f"Error deleting from ChromaDB {db_id}: {e}")

def reset_database():
    """Wipes all data from SQLite and ChromaDB."""
    # Delete all records from SQLite
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM normativas')
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
