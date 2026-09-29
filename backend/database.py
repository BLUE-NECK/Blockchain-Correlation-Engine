import sqlite3
import os

DB_PATH = "tnf_cl.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS network_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        src_ip TEXT,
        dst_ip TEXT,
        src_port INTEGER,
        dst_port INTEGER,
        txid TEXT,
        geo_country TEXT,
        asn TEXT,
        is_flagged INTEGER DEFAULT 0
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blockchain_txns (
        txid TEXT PRIMARY KEY,
        timestamp TEXT,
        input_addresses TEXT,
        output_addresses TEXT,
        input_amounts TEXT,
        output_amounts TEXT,
        fee REAL,
        script_type TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wallets (
        address TEXT PRIMARY KEY,
        total_sent REAL DEFAULT 0,
        total_received REAL DEFAULT 0,
        tx_count INTEGER DEFAULT 0,
        cluster_id TEXT,
        risk_score REAL DEFAULT 0,
        is_peeling INTEGER DEFAULT 0,
        anomaly_score REAL DEFAULT 0,
        reasons TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS correlation_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        total_rows INTEGER,
        correlated_rows INTEGER,
        failed_rows INTEGER,
        timestamp TEXT
    )
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
