import sqlite3
import json
import time
from ai_extractor_openai import extract_metadata_and_summary as extract_openai
from ai_extractor_deepseek import extract_metadata_and_summary as extract_deepseek
import os

# Script para segmentar documentos antiguos usando la IA (OpenAI o DeepSeek)
DB_PATH = "normativas.db"

def backfill_articulos(engine="OpenAI"):
    print(f"Iniciando escaneo retroactivo de artículos usando {engine}...")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Buscar normativas que no tengan ningún articulo asociado aún
    cursor.execute('''
        SELECT n.id, n.numero, n.texto_completo 
        FROM normativas n
        LEFT JOIN articulos a ON n.id = a.normativa_id
        WHERE a.id IS NULL
    ''')
    
    normativas = cursor.fetchall()
    total = len(normativas)
    print(f"Se encontraron {total} documentos sin estructurar.")
    
    for i, norma in enumerate(normativas):
        n_id = norma['id']
        n_num = norma['numero']
        texto = norma['texto_completo']
        
        print(f"[{i+1}/{total}] Segmentando norma ID {n_id} (Nº {n_num})...")
        
        try:
            if engine == "OpenAI":
                metadata = extract_openai(texto)
            else:
                metadata = extract_deepseek(texto)
                
            articulos = metadata.get('articulos', [])
            
            if articulos:
                for art in articulos:
                    cursor.execute('''
                        INSERT INTO articulos (normativa_id, numero, texto)
                        VALUES (?, ?, ?)
                    ''', (n_id, art.get('numero', ''), art.get('texto', '')))
                conn.commit()
                print(f"  -> Guardados {len(articulos)} artículos.")
            else:
                print(f"  -> No se encontraron artículos estructurables.")
                
        except Exception as e:
            print(f"  -> Error al procesar: {e}")
            
        time.sleep(1) # Pausa por rate limits
        
    conn.close()
    print("¡Proceso finalizado!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Backfill artículos con IA')
    parser.add_argument('--engine', type=str, default='OpenAI', help='Motor de IA a utilizar (OpenAI o DeepSeek)')
    args = parser.parse_args()
    
    backfill_articulos(args.engine)
