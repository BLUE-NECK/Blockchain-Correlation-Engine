import networkx as nx
import json
import os
import sqlite3
from backend.database import get_db

GRAPH_CACHE_FILE = "data_gen/sample_output/graph.json"

def build_heterogeneous_graph():
    G = nx.DiGraph()
    conn = get_db()
    cursor = conn.cursor()
    
    # Add Network Events & IP -> TXID edges
    cursor.execute("SELECT src_ip, txid, geo_country, asn, is_flagged FROM network_events")
    net_rows = cursor.fetchall()
    for r in net_rows:
        ip = r["src_ip"]
        txid = r["txid"]
        if ip:
            G.add_node(ip, type="IP", country=r["geo_country"], asn=r["asn"], is_flagged=bool(r["is_flagged"]))
            G.add_node(txid, type="TXID")
            G.add_edge(ip, txid, relation="observed_via")
            
    # Add Blockchain Txns & Wallet -> TXID / TXID -> Wallet edges
    cursor.execute("SELECT txid, input_addresses, output_addresses, fee FROM blockchain_txns")
    tx_rows = cursor.fetchall()
    for r in tx_rows:
        txid = r["txid"]
        inputs = json.loads(r["input_addresses"]) if r["input_addresses"] else []
        outputs = json.loads(r["output_addresses"]) if r["output_addresses"] else []
        
        G.add_node(txid, type="TXID", fee=r["fee"])
        
        for inp in inputs:
            G.add_node(inp, type="Wallet")
            G.add_edge(inp, txid, relation="sent_from")
            
        for out in outputs:
            G.add_node(out, type="Wallet")
            G.add_edge(txid, out, relation="received_by")
            
    conn.close()
    
    # Save graph as JSON
    nodes_data = []
    for n, attr in G.nodes(data=True):
        nodes_data.append({"id": n, **attr})
        
    edges_data = []
    for u, v, attr in G.edges(data=True):
        edges_data.append({"source": u, "target": v, **attr})
        
    graph_dict = {"nodes": nodes_data, "links": edges_data}
    os.makedirs(os.path.dirname(GRAPH_CACHE_FILE), exist_ok=True)
    with open(GRAPH_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(graph_dict, f)
        
    print(f"Graph built with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")
    return G

def load_graph():
    if not os.path.exists(GRAPH_CACHE_FILE):
        return build_heterogeneous_graph()
    
    with open(GRAPH_CACHE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    G = nx.DiGraph()
    for n in data["nodes"]:
        node_id = n["id"]
        attrs = {k: v for k, v in n.items() if k != "id"}
        G.add_node(node_id, **attrs)
        
    for e in data["links"]:
        G.add_edge(e["source"], e["target"], relation=e.get("relation", ""))
        
    return G

def get_subgraph_around_node(node_id, radius=2):
    G = load_graph()
    if node_id not in G:
        return {"nodes": [], "links": []}
        
    sub_nodes = set([node_id])
    current_layer = set([node_id])
    
    for _ in range(radius):
        next_layer = set()
        for n in current_layer:
            neighbors = set(G.successors(n)).union(set(G.predecessors(n)))
            next_layer.update(neighbors)
        sub_nodes.update(next_layer)
        current_layer = next_layer
        
    subG = G.subgraph(sub_nodes)
    
    nodes = []
    for n in subG.nodes():
        nodes.append({"id": n, **subG.nodes[n]})
        
    links = []
    for u, v in subG.edges():
        links.append({"source": u, "target": v, **subG.edges[u, v]})
        
    return {"nodes": nodes, "links": links}
