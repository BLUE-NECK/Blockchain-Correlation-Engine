import csv
import json
import xml.etree.ElementTree as ET
import os
import sqlite3
import datetime
from backend.database import get_db, init_db

def load_asn_map(asn_file="data_gen/sample_output/asn_lookup.csv"):
    asn_map = {}
    if os.path.exists(asn_file):
        with open(asn_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                asn_map[row["asn"]] = {
                    "country": row["country"],
                    "is_flagged": row["is_flagged"].lower() == "true"
                }
    return asn_map

def parse_input_file(file_path):
    rows = []
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == ".csv":
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
    elif ext == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict) and "transactions" in data:
                rows = data["transactions"]
    elif ext == ".xml":
        tree = ET.parse(file_path)
        root = tree.getroot()
        for elem in root.findall("transaction"):
            row = {}
            for child in elem:
                row[child.tag] = child.text
            rows.append(row)
    else:
        raise ValueError(f"Unsupported file format: {ext}")
        
    return rows

def process_and_ingest(file_path, asn_file="data_gen/sample_output/asn_lookup.csv"):
    init_db()
    conn = get_db()
    cursor = conn.cursor()
    
    # Clear existing data
    cursor.execute("DELETE FROM network_events")
    cursor.execute("DELETE FROM blockchain_txns")
    cursor.execute("DELETE FROM wallets")
    cursor.execute("DELETE FROM correlation_logs")
    conn.commit()

    asn_map = load_asn_map(asn_file)
    raw_rows = parse_input_file(file_path)
    
    total_rows = len(raw_rows)
    correlated_count = 0
    failed_count = 0
    
    wallet_stats = {} # address -> {sent, rec, count}

    for r in raw_rows:
        try:
            txid = r.get("txid")
            timestamp = r.get("timestamp")
            src_ip = r.get("src_ip")
            dst_ip = r.get("dst_ip")
            src_port = int(r.get("src_port", 0))
            dst_port = int(r.get("dst_port", 0))
            
            asn = r.get("asn", "AS1001")
            asn_info = asn_map.get(asn, {"country": r.get("geo_country", "US"), "is_flagged": False})
            geo_country = asn_info["country"]
            is_flagged = 1 if asn_info["is_flagged"] else 0
            
            # Parse addresses and amounts
            in_addrs = json.loads(r["input_addresses"]) if isinstance(r["input_addresses"], str) and r["input_addresses"].startswith("[") else ([r["input_addresses"]] if r.get("input_addresses") else [])
            out_addrs = json.loads(r["output_addresses"]) if isinstance(r["output_addresses"], str) and r["output_addresses"].startswith("[") else ([r["output_addresses"]] if r.get("output_addresses") else [])
            
            in_amts = json.loads(r["input_amounts"]) if isinstance(r["input_amounts"], str) and r["input_amounts"].startswith("[") else ([float(r["input_amounts"])] if r.get("input_amounts") else [])
            out_amts = json.loads(r["output_amounts"]) if isinstance(r["output_amounts"], str) and r["output_amounts"].startswith("[") else ([float(r["output_amounts"])] if r.get("output_amounts") else [])
            
            fee = float(r.get("fee", 0.0001))
            script_type = r.get("script_type", "P2PKH")
            
            if not txid or not timestamp:
                failed_count += 1
                continue

            # Insert network event
            cursor.execute("""
                INSERT INTO network_events (timestamp, src_ip, dst_ip, src_port, dst_port, txid, geo_country, asn, is_flagged)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (timestamp, src_ip, dst_ip, src_port, dst_port, txid, geo_country, asn, is_flagged))

            # Insert blockchain txn
            cursor.execute("""
                INSERT OR REPLACE INTO blockchain_txns (txid, timestamp, input_addresses, output_addresses, input_amounts, output_amounts, fee, script_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (txid, timestamp, json.dumps(in_addrs), json.dumps(out_addrs), json.dumps(in_amts), json.dumps(out_amts), fee, script_type))

            # Accumulate wallet stats
            for idx, addr in enumerate(in_addrs):
                amt = in_amts[idx] if idx < len(in_amts) else 0.0
                if addr not in wallet_stats:
                    wallet_stats[addr] = {"total_sent": 0.0, "total_received": 0.0, "tx_count": 0}
                wallet_stats[addr]["total_sent"] += amt
                wallet_stats[addr]["tx_count"] += 1

            for idx, addr in enumerate(out_addrs):
                amt = out_amts[idx] if idx < len(out_amts) else 0.0
                if addr not in wallet_stats:
                    wallet_stats[addr] = {"total_sent": 0.0, "total_received": 0.0, "tx_count": 0}
                wallet_stats[addr]["total_received"] += amt
                wallet_stats[addr]["tx_count"] += 1

            correlated_count += 1
        except Exception as e:
            failed_count += 1

    # Insert wallets
    for addr, stats in wallet_stats.items():
        cursor.execute("""
            INSERT OR REPLACE INTO wallets (address, total_sent, total_received, tx_count)
            VALUES (?, ?, ?, ?)
        """, (addr, stats["total_sent"], stats["total_received"], stats["tx_count"]))

    # Log correlation results
    cursor.execute("""
        INSERT INTO correlation_logs (total_rows, correlated_rows, failed_rows, timestamp)
        VALUES (?, ?, ?, ?)
    """, (total_rows, correlated_count, failed_count, datetime.datetime.now().isoformat()))

    conn.commit()
    conn.close()
    
    print(f"Ingested {correlated_count}/{total_rows} rows into database. Correlation failures: {failed_count}")
    return correlated_count, failed_count
