import json
import sqlite3
import numpy as np
import networkx as nx
from sklearn.ensemble import IsolationForest
from backend.database import get_db
from backend.graph import load_graph
from models.cross_attention import TNFCLCrossAttentionFusion


def detect_entity_clusters(conn):
    """
    Co-input heuristic: wallets that appear together as inputs
    in the same transaction likely belong to the same entity.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT input_addresses FROM blockchain_txns")
    rows = cursor.fetchall()

    co_input_graph = nx.Graph()
    for r in rows:
        addrs = json.loads(r["input_addresses"]) if r["input_addresses"] else []
        if len(addrs) > 1:
            for i in range(len(addrs)):
                for j in range(i + 1, len(addrs)):
                    co_input_graph.add_edge(addrs[i], addrs[j])

    clusters = list(nx.connected_components(co_input_graph))
    cluster_map = {}  # wallet -> cluster_id
    for idx, comp in enumerate(clusters):
        cid = f"CLUSTER_{idx+1:03d}"
        for w in comp:
            cluster_map[w] = cid

    return cluster_map


def detect_peeling_chains(conn):
    """
    Detects peeling chains:
    - 1 input → exactly 2 outputs
    - The ratio of the larger to smaller output >= 2.0
      (lowered from 3.0 for better recall on real data)
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT txid, input_addresses, output_addresses, input_amounts, output_amounts "
        "FROM blockchain_txns"
    )
    rows = cursor.fetchall()

    peeling_wallets = set()
    for r in rows:
        inputs   = json.loads(r["input_addresses"])  if r["input_addresses"]  else []
        outputs  = json.loads(r["output_addresses"]) if r["output_addresses"] else []
        out_amts = json.loads(r["output_amounts"])   if r["output_amounts"]   else []

        if len(inputs) == 1 and len(outputs) == 2 and len(out_amts) == 2:
            o1, o2 = out_amts[0], out_amts[1]
            if o1 > 0 and o2 > 0:
                ratio = max(o1, o2) / min(o1, o2)
                if ratio >= 2.0:
                    peeling_wallets.update([inputs[0], outputs[0], outputs[1]])

    return peeling_wallets


def detect_coinjoin_mixers(conn):
    """
    CoinJoin / mixer fingerprint:
    - >= 5 inputs AND >= 5 outputs
    - All output amounts are nearly equal (coefficient of variation < 2%)
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT input_addresses, output_addresses, output_amounts "
        "FROM blockchain_txns"
    )
    rows = cursor.fetchall()

    mixer_wallets = set()
    for r in rows:
        inputs   = json.loads(r["input_addresses"])  if r["input_addresses"]  else []
        outputs  = json.loads(r["output_addresses"]) if r["output_addresses"] else []
        out_amts = json.loads(r["output_amounts"])   if r["output_amounts"]   else []

        if len(inputs) >= 5 and len(outputs) >= 5 and len(out_amts) >= 5:
            arr = [a for a in out_amts if a > 0]
            if len(arr) >= 5:
                mean_out = sum(arr) / len(arr)
                std_out  = (sum((x - mean_out) ** 2 for x in arr) / len(arr)) ** 0.5
                # Near-equal outputs → CoinJoin
                if mean_out > 0 and (std_out / mean_out) < 0.02:
                    mixer_wallets.update(inputs)
                    mixer_wallets.update(outputs)

    return mixer_wallets


def detect_darknet_patterns(conn):
    """
    Darknet-market micro-payment pattern:
    - Wallet receives >= 5 small payments (< 0.1 BTC each)
    - All routed through flagged-ASN IPs
    Typical vendor/market wallet fingerprint.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.output_addresses, b.output_amounts, n.is_flagged
        FROM blockchain_txns b
        LEFT JOIN network_events n ON b.txid = n.txid
    """)
    rows = cursor.fetchall()

    vendor_counts = {}  # wallet -> count of small flagged-ASN incoming payments
    for r in rows:
        if not r["is_flagged"]:
            continue
        out_addrs = json.loads(r["output_addresses"]) if r["output_addresses"] else []
        out_amts  = json.loads(r["output_amounts"])   if r["output_amounts"]   else []
        for i, addr in enumerate(out_addrs):
            amt = out_amts[i] if i < len(out_amts) else 0
            if 0 < amt < 0.1:
                vendor_counts[addr] = vendor_counts.get(addr, 0) + 1

    return {w for w, cnt in vendor_counts.items() if cnt >= 5}


def compute_anomaly_scores(conn):
    """
    IsolationForest anomaly detection on wallet behavioural features.
    Returns dict: wallet_address -> normalized anomaly score [0, 1].
    """
    cursor = conn.cursor()
    cursor.execute("SELECT address, total_sent, total_received, tx_count FROM wallets")
    rows = cursor.fetchall()

    if not rows:
        return {}

    wallets = [r["address"] for r in rows]
    feature_matrix = []
    for r in rows:
        sent  = r["total_sent"]
        rec   = r["total_received"]
        cnt   = r["tx_count"]
        ratio = (rec + 0.0001) / (sent + 0.0001)
        delta = abs(sent - rec)
        feature_matrix.append([cnt, sent, rec, ratio, delta])

    X = np.array(feature_matrix)
    clf = IsolationForest(contamination=0.15, random_state=42)
    clf.fit(X)
    scores = -clf.decision_function(X)  # higher = more anomalous

    min_s, max_s = np.min(scores), np.max(scores)
    norm = (scores - min_s) / (max_s - min_s) if max_s > min_s else np.zeros(len(scores))

    return {wallets[i]: float(norm[i]) for i in range(len(wallets))}


def compute_pagerank_proximity(G, seed_wallets):
    """
    Personalized PageRank: nodes closer to known-bad wallets get higher scores.
    Returns dict: wallet_address -> normalized proximity score [0, 1].
    """
    if not G.number_of_nodes() or not seed_wallets:
        return {}

    valid_seeds = [s for s in seed_wallets if s in G]
    if not valid_seeds:
        return {}

    personalization = {
        n: (1.0 / len(valid_seeds) if n in valid_seeds else 0.0)
        for n in G.nodes()
    }
    try:
        pr = nx.pagerank(G, alpha=0.85, personalization=personalization)
        max_pr = max(pr.values()) if pr else 1.0
        return {
            n: pr[n] / max_pr
            for n in pr
            if G.nodes[n].get("type") == "Wallet"
        }
    except Exception:
        return {}


def run_ml_pipeline():
    conn = get_db()
    cursor = conn.cursor()

    # 1. Entity Clustering (co-input heuristic)
    cluster_map = detect_entity_clusters(conn)

    # 2. Peeling Chain Detection
    peeling_wallets = detect_peeling_chains(conn)

    # 3. CoinJoin / Mixer Detection
    mixer_wallets = detect_coinjoin_mixers(conn)

    # 4. Darknet Market Micro-Payment Detection
    darknet_wallets = detect_darknet_patterns(conn)

    # 5. IsolationForest Anomaly Scoring
    anomaly_scores = compute_anomaly_scores(conn)

    # 6. Flagged ASN Hits per Wallet
    cursor.execute("""
        SELECT n.is_flagged, n.asn, b.input_addresses, b.output_addresses
        FROM network_events n
        JOIN blockchain_txns b ON n.txid = b.txid
    """)
    net_rows = cursor.fetchall()
    flagged_asn_wallets = {}  # wallet -> set of flagged ASNs
    for r in net_rows:
        if r["is_flagged"]:
            asn = r["asn"]
            in_a  = json.loads(r["input_addresses"])  if r["input_addresses"]  else []
            out_a = json.loads(r["output_addresses"]) if r["output_addresses"] else []
            for w in in_a + out_a:
                flagged_asn_wallets.setdefault(w, set()).add(asn)

    # 7. Personalized PageRank proximity to all known bad seeds
    G = load_graph()
    all_seeds = (
        list(peeling_wallets)
        + list(mixer_wallets)
        + list(darknet_wallets)
        + list(flagged_asn_wallets.keys())
    )
    proximity_scores = compute_pagerank_proximity(G, all_seeds)

    # Optional Cross-Attention Model
    fusion_model = TNFCLCrossAttentionFusion()

    # ---- Compute composite risk score for every wallet ----
    cursor.execute("SELECT address, total_sent, total_received, tx_count FROM wallets")
    all_wallets = cursor.fetchall()

    for r in all_wallets:
        w       = r["address"]
        reasons = []
        score   = 0.0

        # A: Flagged ASN (+20)
        flagged_asns = flagged_asn_wallets.get(w, set())
        if flagged_asns:
            asn_str = ", ".join(sorted(flagged_asns))
            score += 20.0
            reasons.append(f"Flagged ASN detected ({asn_str}) → +20")

        # B: Peeling chain (+30)
        is_peel = w in peeling_wallets
        if is_peel:
            score += 30.0
            reasons.append("Matches peeling-chain transaction pattern → +30")

        # C: CoinJoin / Mixer (+25)
        if w in mixer_wallets:
            score += 25.0
            reasons.append("Involved in CoinJoin / mixer transaction → +25")

        # D: Darknet micro-payment pattern (+20)
        if w in darknet_wallets:
            score += 20.0
            reasons.append("Repeated micro-payments via flagged ASN (darknet pattern) → +20")

        # E: Anomaly score (+25 max)
        anom        = anomaly_scores.get(w, 0.0)
        anom_contrib = round(anom * 25.0, 1)
        if anom_contrib > 5.0:
            score += anom_contrib
            reasons.append(f"High anomaly score ({anom:.2f}) → +{anom_contrib}")

        # F: PageRank proximity (+25 max)
        prox        = proximity_scores.get(w, 0.0)
        prox_contrib = round(prox * 25.0, 1)
        if prox_contrib > 5.0:
            score += prox_contrib
            reasons.append(f"High graph proximity to flagged entity ({prox:.2f}) → +{prox_contrib}")

        # Cross-Attention refinement (future integration point)
        fusion_model.predict_fusion_risk(
            [8333, 1001, 1, 1 if flagged_asns else 0],
            [r["total_sent"], r["total_received"], r["tx_count"], 1.0]
        )

        final_score = min(100.0, round(score, 1))
        cid = cluster_map.get(w, "")

        cursor.execute("""
            UPDATE wallets
            SET cluster_id = ?, risk_score = ?, is_peeling = ?, anomaly_score = ?, reasons = ?
            WHERE address = ?
        """, (cid, final_score, 1 if is_peel else 0, round(anom, 2), json.dumps(reasons), w))

    conn.commit()
    conn.close()

    print("ML detection and risk scoring completed.")
    print(f"  Peeling wallets  : {len(peeling_wallets)}")
    print(f"  Mixer wallets    : {len(mixer_wallets)}")
    print(f"  Darknet wallets  : {len(darknet_wallets)}")
    print(f"  Flagged ASN walls: {len(flagged_asn_wallets)}")
