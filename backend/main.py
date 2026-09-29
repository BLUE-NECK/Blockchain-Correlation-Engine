import os
import json
import sqlite3
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.database import get_db, init_db
from backend.ingest import process_and_ingest
from backend.graph import build_heterogeneous_graph, get_subgraph_around_node, GRAPH_CACHE_FILE
from backend.detectors import run_ml_pipeline

app = FastAPI(title="TNF-CL API", description="Temporal Network-Fusion Cross-attention Ledger Prototype Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    init_db()

# -----------------------------------------------------------------------
# Health check endpoint — for UptimeRobot / uptime monitoring
# GET /health  →  200 OK  { status: "ok", ... }
# -----------------------------------------------------------------------
@app.get("/health")
def health_check():
    import datetime
    return {
        "status": "ok",
        "service": "TNF-CL Bitcoin Network Correlation Engine",
        "version": "1.0.0",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    }


@app.post("/ingest")
async def run_ingest(file_path: str = "data_gen/sample_output/transactions.csv"):
    if not os.path.exists(file_path):
        # Generate enhanced dataset if missing
        from data_gen.generate_dataset import generate_dataset
        generate_dataset(num_rows=2000, output_dir="data_gen/sample_output")
        file_path = "data_gen/sample_output/transactions.csv"
        
    correlated, failed = process_and_ingest(file_path)
    build_heterogeneous_graph()
    run_ml_pipeline()
    
    return {
        "status": "success",
        "message": "Ingestion, graph construction, and ML analysis completed.",
        "correlated_txns": correlated,
        "failed_txns": failed
    }

@app.get("/stats")
def get_stats():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM network_events")
    total_txns = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM wallets")
    total_wallets = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM wallets WHERE risk_score >= 40.0")
    flagged_wallets = cursor.fetchone()[0]
    
    cursor.execute("SELECT MAX(risk_score) FROM wallets")
    max_score = cursor.fetchone()[0] or 0.0
    
    # Risk bands distribution
    cursor.execute("SELECT COUNT(*) FROM wallets WHERE risk_score < 25.0")
    low_risk = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM wallets WHERE risk_score >= 25.0 AND risk_score < 50.0")
    med_risk = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM wallets WHERE risk_score >= 50.0 AND risk_score < 75.0")
    high_risk = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM wallets WHERE risk_score >= 75.0")
    critical_risk = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "total_transactions": total_txns,
        "total_wallets": total_wallets,
        "flagged_wallets": flagged_wallets,
        "highest_risk_score": max_score,
        "risk_bands": {
            "Low (0-24)": low_risk,
            "Medium (25-49)": med_risk,
            "High (50-74)": high_risk,
            "Critical (75-100)": critical_risk
        }
    }

@app.get("/alerts")
def get_alerts():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT address, risk_score, is_peeling, anomaly_score, reasons, cluster_id, total_sent, total_received, tx_count
        FROM wallets
        WHERE risk_score > 0
        ORDER BY risk_score DESC
        LIMIT 100
    """)
    rows = cursor.fetchall()
    conn.close()
    
    alerts = []
    for r in rows:
        reasons_list = json.loads(r["reasons"]) if r["reasons"] else []
        top_reason = reasons_list[0] if reasons_list else "Elevated risk characteristics"
        
        score = r["risk_score"]
        confidence = min(0.99, max(0.50, round(score / 100.0 + 0.1, 2)))
        
        alerts.append({
            "wallet": r["address"],
            "risk_score": score,
            "confidence": confidence,
            "top_reason": top_reason,
            "all_reasons": reasons_list,
            "cluster_id": r["cluster_id"],
            "is_peeling": bool(r["is_peeling"]),
            "tx_count": r["tx_count"]
        })
        
    return alerts

@app.get("/wallet/{wallet_id}")
def get_wallet_detail(wallet_id: str):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM wallets WHERE address = ?", (wallet_id,))
    w_row = cursor.fetchone()
    
    if not w_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Wallet not found")
        
    # Get associated transactions with full input/output data
    cursor.execute("""
        SELECT b.txid, b.timestamp, b.input_addresses, b.output_addresses,
               b.input_amounts, b.output_amounts, b.fee, b.script_type,
               n.src_ip, n.asn, n.geo_country, n.is_flagged
        FROM blockchain_txns b
        LEFT JOIN network_events n ON b.txid = n.txid
        WHERE b.input_addresses LIKE ? OR b.output_addresses LIKE ?
        ORDER BY b.timestamp DESC
        LIMIT 50
    """, (f"%{wallet_id}%", f"%{wallet_id}%"))
    tx_rows = cursor.fetchall()
    conn.close()
    
    txns = []
    connected_ips = set()
    for tr in tx_rows:
        if tr["src_ip"]:
            connected_ips.add(f"{tr['src_ip']} ({tr['asn'] or 'Unknown ASN'}, {tr['geo_country'] or 'XX'})")

        # Parse full addresses and amounts
        in_addrs  = json.loads(tr["input_addresses"])  if tr["input_addresses"]  else []
        out_addrs = json.loads(tr["output_addresses"]) if tr["output_addresses"] else []
        in_amts   = json.loads(tr["input_amounts"])    if tr["input_amounts"]    else []
        out_amts  = json.loads(tr["output_amounts"])   if tr["output_amounts"]   else []

        # Pair addresses with amounts for clarity
        inputs_detail  = [{"address": addr, "amount_btc": in_amts[i] if i < len(in_amts) else 0}
                          for i, addr in enumerate(in_addrs)]
        outputs_detail = [{"address": addr, "amount_btc": out_amts[i] if i < len(out_amts) else 0}
                          for i, addr in enumerate(out_addrs)]

        txns.append({
            "txid":          tr["txid"],
            "timestamp":     tr["timestamp"],
            "inputs":        inputs_detail,
            "outputs":       outputs_detail,
            "fee":           tr["fee"],
            "script_type":   tr["script_type"] if tr["script_type"] else "Unknown",
            "ip":            tr["src_ip"],
            "asn":           tr["asn"],
            "country":       tr["geo_country"],
            "is_flagged_ip": bool(tr["is_flagged"])
        })
        
    reasons_list = json.loads(w_row["reasons"]) if w_row["reasons"] else []
    
    return {
        "wallet":          w_row["address"],
        "risk_score":      w_row["risk_score"],
        "anomaly_score":   w_row["anomaly_score"],
        "is_peeling":      bool(w_row["is_peeling"]),
        "cluster_id":      w_row["cluster_id"],
        "total_sent":      w_row["total_sent"],
        "total_received":  w_row["total_received"],
        "tx_count":        w_row["tx_count"],
        "risk_breakdown":  reasons_list,
        "connected_ips":   list(connected_ips),
        "transactions":    txns
    }

@app.get("/graph/{node_id}")
def get_graph(node_id: str):
    if node_id == "full":
        if os.path.exists(GRAPH_CACHE_FILE):
            with open(GRAPH_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Limit size for smooth canvas rendering
                return {
                    "nodes": data["nodes"][:300],
                    "links": data["links"][:400]
                }
        return {"nodes": [], "links": []}
        
    return get_subgraph_around_node(node_id, radius=2)


# -----------------------------------------------------------------------
# NEW: Detailed node information endpoint (used by graph hover tooltips)
# -----------------------------------------------------------------------
@app.get("/node/{node_id:path}")
def get_node_detail(node_id: str):
    """
    Returns detailed info for any graph node (IP, Wallet, or TXID).
    Called by the frontend graph canvas on hover to populate the tooltip.
    """
    conn = get_db()
    cursor = conn.cursor()
    result = {"id": node_id, "type": "Unknown", "details": {}}

    # --- Try: IP node ---
    cursor.execute("""
        SELECT src_ip, COUNT(*) as event_count,
               GROUP_CONCAT(DISTINCT geo_country) as countries,
               GROUP_CONCAT(DISTINCT asn) as asns,
               MAX(is_flagged) as is_flagged,
               GROUP_CONCAT(DISTINCT txid) as txids
        FROM network_events
        WHERE src_ip = ?
        GROUP BY src_ip
    """, (node_id,))
    ip_row = cursor.fetchone()
    if ip_row and ip_row["src_ip"]:
        result["type"] = "IP"
        result["details"] = {
            "ip_address":    ip_row["src_ip"],
            "event_count":   ip_row["event_count"],
            "countries":     ip_row["countries"],
            "asns":          ip_row["asns"],
            "is_flagged":    bool(ip_row["is_flagged"]),
            "linked_txids":  ip_row["txids"].split(",") if ip_row["txids"] else []
        }
        conn.close()
        return result

    # --- Try: TXID node ---
    cursor.execute("""
        SELECT b.txid, b.timestamp, b.input_addresses, b.output_addresses,
               b.input_amounts, b.output_amounts, b.fee, b.script_type,
               n.src_ip, n.asn, n.geo_country, n.is_flagged
        FROM blockchain_txns b
        LEFT JOIN network_events n ON b.txid = n.txid
        WHERE b.txid = ?
        LIMIT 1
    """, (node_id,))
    tx_row = cursor.fetchone()
    if tx_row:
        in_addrs  = json.loads(tx_row["input_addresses"])  if tx_row["input_addresses"]  else []
        out_addrs = json.loads(tx_row["output_addresses"]) if tx_row["output_addresses"] else []
        in_amts   = json.loads(tx_row["input_amounts"])    if tx_row["input_amounts"]    else []
        out_amts  = json.loads(tx_row["output_amounts"])   if tx_row["output_amounts"]   else []

        total_in  = sum(in_amts)
        total_out = sum(out_amts)

        inputs_detail  = [{"address": a, "amount_btc": in_amts[i]  if i < len(in_amts)  else 0}
                          for i, a in enumerate(in_addrs)]
        outputs_detail = [{"address": a, "amount_btc": out_amts[i] if i < len(out_amts) else 0}
                          for i, a in enumerate(out_addrs)]

        result["type"] = "TXID"
        result["details"] = {
            "txid":         tx_row["txid"],
            "timestamp":    tx_row["timestamp"],
            "inputs":       inputs_detail,
            "outputs":      outputs_detail,
            "total_in_btc": round(total_in, 8),
            "total_out_btc":round(total_out, 8),
            "fee_btc":      tx_row["fee"],
            "script_type":  tx_row["script_type"] or "Unknown",
            "observed_ip":  tx_row["src_ip"],
            "asn":          tx_row["asn"],
            "country":      tx_row["geo_country"],
            "is_flagged_ip":bool(tx_row["is_flagged"]),
            "n_inputs":     len(in_addrs),
            "n_outputs":    len(out_addrs),
        }
        conn.close()
        return result

    # --- Try: Wallet node ---
    cursor.execute("SELECT * FROM wallets WHERE address = ?", (node_id,))
    w_row = cursor.fetchone()
    if w_row:
        reasons_list = json.loads(w_row["reasons"]) if w_row["reasons"] else []
        result["type"] = "Wallet"
        result["details"] = {
            "address":        w_row["address"],
            "total_sent":     round(w_row["total_sent"],     8),
            "total_received": round(w_row["total_received"], 8),
            "tx_count":       w_row["tx_count"],
            "risk_score":     w_row["risk_score"],
            "anomaly_score":  w_row["anomaly_score"],
            "is_peeling":     bool(w_row["is_peeling"]),
            "cluster_id":     w_row["cluster_id"] or "None",
            "risk_reasons":   reasons_list,
        }
        conn.close()
        return result

    conn.close()
    raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found in any table.")


# Serve static frontend files if directory exists
if os.path.exists("frontend"):
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
