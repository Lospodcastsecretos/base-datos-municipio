import sqlite3
import re
import json

def backfill_juridico():
    conn = sqlite3.connect('normativas.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, texto_completo, relaciones_juridicas FROM normativas")
    rows = cursor.fetchall()
    
    updated = 0
    # Regex to find verbs followed by ordinance/decree and a number within a short window
    # Examples: "derógase la ordenanza 123", "modifica el art 2 de la ord 456"
    pattern = re.compile(r'(?i)(deroga|modifica|sustituye|reglamenta|suspende|prorroga|complementa)[\s\w,]{0,60}?(?:ordenanza|decreto|ley)[\sNº°]*(?:numero\s*)?(\d+)')
    
    for row in rows:
        db_id, texto, rels_str = row
        if not texto: continue
        
        # Skip if already has deepseek relations
        if rels_str and rels_str != '[]' and rels_str != 'None':
            continue
            
        matches = pattern.findall(texto)
        
        if matches:
            relaciones = []
            for accion, numero in matches:
                # Normalizar accion
                accion_norm = accion.lower().strip()
                if 'deroga' in accion_norm: accion_norm = 'deroga'
                elif 'modifica' in accion_norm: accion_norm = 'modifica'
                
                relaciones.append({
                    "norma_destino": numero,
                    "accion": accion_norm,
                    "detalle": f"Detectado por Regex rápido: {accion_norm} norma {numero}"
                })
                
            # Eliminar duplicados
            unique_rels = []
            seen = set()
            for r in relaciones:
                key = f"{r['accion']}-{r['norma_destino']}"
                if key not in seen:
                    seen.add(key)
                    unique_rels.append(r)
            
            cursor.execute("UPDATE normativas SET relaciones_juridicas = ? WHERE id = ?", (json.dumps(unique_rels), db_id))
            updated += 1
            
    conn.commit()
    conn.close()
    print(f"Updated {updated} records using advanced Regex fallback.")

if __name__ == '__main__':
    backfill_juridico()
