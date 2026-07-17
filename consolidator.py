import sqlite3
import json
import os
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "normativas.db"

def run_consolidation():
    print("Iniciando motor de consolidación temporal...")
    
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: No se ha configurado la variable OPENAI_API_KEY en el archivo .env")
        return
        
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. Obtener todas las normativas ordenadas por fecha (antiguas primero) para consolidar en orden
    cursor.execute("SELECT * FROM normativas ORDER BY COALESCE(fecha, '1900-01-01') ASC")
    normativas = cursor.fetchall()
    
    # Lista de acciones modificadoras que disparan la consolidación
    acciones_modificadoras = ["modifica", "sustituye", "deroga parcial", "incorpora", "suprime", "complementa", "prorroga", "suspende"]
    
    consolidaciones_realizadas = 0
    
    for norma in normativas:
        n_id = norma['id']
        n_num = norma['numero']
        n_tipo = norma['tipo_nombre']
        n_fecha = norma['fecha'] or '2000-01-01'
        n_texto = norma['texto_completo']
        
        rels_str = norma['relaciones_juridicas']
        if not rels_str:
            continue
            
        try:
            rels = json.loads(rels_str)
        except Exception:
            continue
            
        if not isinstance(rels, list):
            continue
            
        for rel in rels:
            destino_num = rel.get('norma_destino')
            accion = str(rel.get('accion')).lower().strip()
            detalle = rel.get('detalle', '')
            
            if not destino_num or accion not in acciones_modificadoras:
                continue
                
            # Buscar la norma destino en la base de datos
            # Hacemos una búsqueda aproximada por número
            cursor.execute("SELECT * FROM normativas WHERE numero = ? LIMIT 1", (destino_num,))
            destino_norma = cursor.fetchone()
            
            if not destino_norma:
                print(f"Norma destino Nº {destino_num} no encontrada en la base de datos. Saltando relación.")
                continue
                
            dest_id = destino_norma['id']
            dest_num = destino_norma['numero']
            dest_tipo = destino_norma['tipo_nombre']
            
            # Verificar si esta modificación ya fue aplicada anteriormente
            # Buscamos si existe alguna versión en 'articulos' para la norma destino que tenga como fuente esta norma
            cursor.execute("SELECT COUNT(*) FROM articulos WHERE normativa_id = ? AND fuente_normativa_id = ?", (dest_id, n_id))
            if cursor.fetchone()[0] > 0:
                # Ya fue aplicada
                continue
                
            print(f"\n[Consolidando] La norma Nº {n_num} ({n_tipo}) {accion} a la norma Nº {dest_num} ({dest_tipo})")
            print(f" -> Detalle: {detalle}")
            
            # Obtener los artículos vigentes de la norma destino justo antes de la fecha de la norma modificadora
            cursor.execute('''
                SELECT * FROM articulos 
                WHERE normativa_id = ? 
                  AND (fecha_desde <= ? OR fecha_desde IS NULL OR fecha_desde = '')
                  AND (fecha_hasta > ? OR fecha_hasta IS NULL OR fecha_hasta = '')
                ORDER BY CAST(numero AS INTEGER), numero ASC
            ''', (dest_id, n_fecha, n_fecha))
            articulos_vigentes = cursor.fetchall()
            
            if not articulos_vigentes:
                print(f" -> Advertencia: La norma Nº {dest_num} no tiene artículos cargados aún. No se puede consolidar.")
                continue
                
            # Construir el texto de los artículos vigentes para presentarlo a la IA
            articulos_vigentes_txt = ""
            for art in articulos_vigentes:
                articulos_vigentes_txt += f"Artículo {art['numero']}: {art['texto']}\n\n"
                
            # Llamar a OpenAI para que aplique la modificación
            prompt_sistema = """
            Eres un consolidador de textos legales. Tu tarea es aplicar las modificaciones del documento nuevo sobre los artículos existentes de la norma destino.
            Debes devolver ESTRICTAMENTE un objeto JSON válido que indique los artículos que cambian, se eliminan (suprimen) o se agregan (incorporan).
            Formato de salida esperado:
            {
              "articulos_actualizados": [
                {"numero": "3", "accion": "modifica", "texto": "Nuevo texto del articulo 3 actualizado..."},
                {"numero": "4", "accion": "suprime", "texto": ""},
                {"numero": "5", "accion": "incorpora", "texto": "Texto del nuevo articulo incorporado..."}
              ]
            }
            Si un artículo es modificado o sustituido, la acción es "modifica" y debes proveer el texto actualizado completo.
            Si un artículo es derogado o suprimido, la acción es "suprime" y el texto debe ser vacío.
            Si se agrega un artículo nuevo, la acción es "incorpora" y debes proveer el texto completo.
            """
            
            prompt_usuario = f"""
            Norma Destino Nº {dest_num} ({dest_tipo}) - Artículos Vigentes antes del cambio:
            {articulos_vigentes_txt}
            
            Norma Modificadora Nº {n_num} ({n_tipo}) promulgada el {n_fecha} - Texto completo:
            {n_texto}
            
            Relación de modificación detectada:
            Acción: {accion}
            Detalle: {detalle}
            
            Por favor, genera el JSON con los artículos actualizados.
            """
            
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": prompt_sistema},
                        {"role": "user", "content": prompt_usuario}
                    ],
                    response_format={'type': 'json_object'},
                    temperature=0.1
                )
                
                res_content = response.choices[0].message.content
                data = json.loads(res_content)
                actualizaciones = data.get("articulos_actualizados", [])
                
                for act in actualizaciones:
                    num_art = act.get("numero")
                    act_accion = act.get("accion")
                    nuevo_texto = act.get("texto", "")
                    
                    if not num_art:
                        continue
                        
                    # Buscar la versión activa actual de este artículo en la norma destino
                    cursor.execute('''
                        SELECT * FROM articulos 
                        WHERE normativa_id = ? AND numero = ? AND (fecha_hasta IS NULL OR fecha_hasta = '')
                        ORDER BY version_numero DESC LIMIT 1
                    ''', (dest_id, num_art))
                    articulo_previo = cursor.fetchone()
                    
                    if act_accion == "suprime":
                        if articulo_previo:
                            # Cerrar versión activa
                            cursor.execute('''
                                UPDATE articulos SET fecha_hasta = ? 
                                WHERE id = ?
                            ''', (n_fecha, articulo_previo['id']))
                            print(f"   [Suprimido] Artículo {num_art} derogado a partir de {n_fecha}")
                    elif act_accion == "modifica":
                        if articulo_previo:
                            # Cerrar versión activa
                            cursor.execute('''
                                UPDATE articulos SET fecha_hasta = ? 
                                WHERE id = ?
                            ''', (n_fecha, articulo_previo['id']))
                            
                            prev_ver = articulo_previo['version_numero']
                            
                            # Insertar nueva versión
                            cursor.execute('''
                                INSERT INTO articulos (normativa_id, numero, texto, version_numero, fecha_desde, fuente_normativa_id)
                                VALUES (?, ?, ?, ?, ?, ?)
                            ''', (dest_id, num_art, nuevo_texto, prev_ver + 1, n_fecha, n_id))
                            print(f"   [Modificado] Artículo {num_art} v{prev_ver + 1} creado a partir de {n_fecha}")
                    elif act_accion == "incorpora":
                        # Insertar nuevo artículo
                        cursor.execute('''
                            INSERT INTO articulos (normativa_id, numero, texto, version_numero, fecha_desde, fuente_normativa_id)
                            VALUES (?, ?, ?, 1, ?, ?)
                        ''', (dest_id, num_art, nuevo_texto, n_fecha, n_id))
                        print(f"   [Incorporado] Artículo {num_art} creado a partir de {n_fecha}")
                        
                conn.commit()
                consolidaciones_realizadas += 1
                
            except Exception as e:
                print(f" -> Error al llamar a OpenAI / consolidar: {e}")
                
            time.sleep(1) # Pequeña pausa
            
    conn.close()
    print(f"\nMotor finalizado. Se aplicaron {consolidaciones_realizadas} consolidaciones en esta ejecución.")

if __name__ == "__main__":
    run_consolidation()
