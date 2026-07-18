import sqlite3
import json
import time
import os
import argparse
import sys
from ai_extractor_openai import extract_metadata_and_summary_openai as extract_openai
from ai_extractor_deepseek import extract_metadata_and_summary_deepseek as extract_deepseek
from ai_extractor import extract_metadata_and_summary as extract_gemini

DB_PATH = "normativas.db"

def backfill_conexiones(engine="OpenAI"):
    print(f"Iniciando escaneo retroactivo de conexiones y referencias usando {engine}...")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Buscar normativas que no tengan referencias guardadas aun
    cursor.execute('''
        SELECT id, numero, tipo_nombre, texto_completo 
        FROM normativas 
        WHERE referencias IS NULL OR referencias = '[]' OR referencias = 'None' OR referencias = ''
    ''')
    
    normativas = cursor.fetchall()
    total = len(normativas)
    print(f"Se encontraron {total} documentos sin conexiones escaneadas.")
    
    for i, norma in enumerate(normativas):
        n_id = norma['id']
        n_num = norma['numero']
        n_tipo = norma['tipo_nombre']
        texto = norma['texto_completo']
        
        print(f"[{i+1}/{total}] Escaneando conexiones de {n_tipo} Nº {n_num}...")
        
        try:
            if engine == "OpenAI":
                metadata = extract_openai(texto)
            elif engine == "DeepSeek":
                metadata = extract_deepseek(texto)
            else:
                metadata = extract_gemini(texto)
                
            refs = metadata.get('referencias', [])
            rels = metadata.get('relaciones_juridicas', [])
            
            cursor.execute('''
                UPDATE normativas 
                SET referencias = ?, relaciones_juridicas = ? 
                WHERE id = ?
            ''', (json.dumps(refs), json.dumps(rels), n_id))
            conn.commit()
            print(f"  -> Conexiones encontradas: {len(refs)} referencias, {len(rels)} relaciones jurídicas.")
            
        except Exception as e:
            print(f"  -> Error al escanear: {e}")
            
        time.sleep(1) # Pausa para evitar rate limits
        
    conn.close()
    print("¡Escaneo de conexiones finalizado!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Backfill conexiones y referencias con IA')
    parser.add_argument('--engine', type=str, default='OpenAI', help='Motor de IA a utilizar (OpenAI, DeepSeek o Gemini)')
    args = parser.parse_args()
    
    backfill_conexiones(args.engine)
