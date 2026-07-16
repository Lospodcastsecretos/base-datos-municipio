import sqlite3
import json
from pyvis.network import Network
import os

DB_PATH = "normativas.db"

def generate_network_graph():
    """Generates an HTML network graph of the documents and their references."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, numero, titulo, referencias, relaciones_juridicas FROM normativas")
    rows = cursor.fetchall()
    conn.close()

    # Create network
    net = Network(height="600px", width="100%", bgcolor="#222222", font_color="white", directed=True, cdn_resources="remote")
    net.force_atlas_2based() # Use a physics engine good for interconnected networks

    # Dictionary to quickly find node IDs by 'numero'
    numero_to_id = {}
    for row in rows:
        db_id, numero, titulo, referencias, relaciones_jur = row
        numero_to_id[str(numero).strip()] = db_id

    # 1. Determine which nodes actually have connections and build edges
    connected_nodes = set()
    edges_to_add = [] # (source, target, color, title)
    
    for row in rows:
        db_id, numero, titulo, referencias_str, relaciones_jur_str = row
        
        # Primero intentamos usar relaciones juridicas avanzadas
        if relaciones_jur_str and relaciones_jur_str != '[]' and relaciones_jur_str != 'None':
            try:
                rels = json.loads(relaciones_jur_str)
                for rel in rels:
                    target_num = str(rel.get("norma_destino")).strip()
                    accion = str(rel.get("accion", "")).lower()
                    detalle = rel.get("detalle", "")
                    
                    if target_num in numero_to_id:
                        target_id = numero_to_id[target_num]
                        if target_id != db_id:
                            # Color coding based on action
                            edge_color = "#888888" # Default
                            if "deroga" in accion:
                                edge_color = "#f44336" # Red
                            elif "modifica" in accion or "sustituye" in accion or "corrige" in accion:
                                edge_color = "#ff9800" # Orange
                            elif "reglamenta" in accion or "aprueba" in accion or "complementa" in accion:
                                edge_color = "#4CAF50" # Green
                            
                            title_html = f"Acción: {accion.upper()}<br>Detalle: {detalle}"
                            edges_to_add.append((db_id, target_id, edge_color, title_html))
                            connected_nodes.add(db_id)
                            connected_nodes.add(target_id)
            except Exception as e:
                pass
        
        # Fallback a referencias simples si no hay relaciones complejas
        elif referencias_str:
            try:
                refs = json.loads(referencias_str)
                if isinstance(refs, list):
                    for ref in refs:
                        ref = str(ref).strip()
                        if ref in numero_to_id:
                            target_id = numero_to_id[ref]
                            if target_id != db_id:
                                edges_to_add.append((db_id, target_id, "#888888", "Referencia general"))
                                connected_nodes.add(db_id)
                                connected_nodes.add(target_id)
            except:
                pass

    # 2. Add only connected nodes
    for row in rows:
        db_id, numero, titulo, _, _ = row
        if db_id in connected_nodes:
            label = f"Norma {numero}" if numero else f"ID {db_id}"
            title = f"{label}\n{titulo}"
            net.add_node(db_id, label=label, title=title, color="#4CAF50")

    # 3. Add the edges
    for source, target, color, title in edges_to_add:
        net.add_edge(source, target, color=color, title=title)

    # Save to HTML file
    html_file = "graph.html"
    net.save_graph(html_file)
    
    # Read the HTML so it can be rendered by Streamlit
    with open(html_file, 'r', encoding='utf-8') as f:
        html_data = f.read()
        
    return html_data
