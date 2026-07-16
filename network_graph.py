import sqlite3
import json
from pyvis.network import Network
import os

DB_PATH = "normativas.db"

def generate_network_graph():
    """Generates an HTML network graph of the documents and their references."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, numero, titulo, referencias FROM normativas")
    rows = cursor.fetchall()
    conn.close()

    # Create network with search/filter UI enabled
    net = Network(height="600px", width="100%", bgcolor="#222222", font_color="white", directed=True, select_menu=True, filter_menu=True, cdn_resources="remote")
    net.force_atlas_2based() # Use a physics engine good for interconnected networks

    # Dictionary to quickly find node IDs by 'numero'
    numero_to_id = {}
    
    # Add nodes
    for row in rows:
        db_id, numero, titulo, referencias = row
        numero_to_id[str(numero).strip()] = db_id
        
        label = f"Norma {numero}" if numero else f"ID {db_id}"
        title = f"{label}\n{titulo}"
        net.add_node(db_id, label=label, title=title, color="#4CAF50")

    # Add edges
    for row in rows:
        db_id, numero, titulo, referencias_str = row
        if not referencias_str:
            continue
            
        try:
            # Parse references (stored as JSON array)
            refs = json.loads(referencias_str)
            if isinstance(refs, list):
                for ref in refs:
                    ref = str(ref).strip()
                    if ref in numero_to_id:
                        target_id = numero_to_id[ref]
                        net.add_edge(db_id, target_id, color="#888888")
        except:
            pass # Ignore malformed references

    # Save to HTML file
    html_file = "graph.html"
    net.save_graph(html_file)
    
    # Read the HTML so it can be rendered by Streamlit
    with open(html_file, 'r', encoding='utf-8') as f:
        html_data = f.read()
        
    return html_data
