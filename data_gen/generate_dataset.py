"""
TNF-CL Enhanced Synthetic Dataset Generator
Generates realistic Bitcoin network + blockchain cross-layer data with:
  - Peeling chains (coin-following laundering pattern)
  - Entity clusters (co-input heuristic groups)
  - Mixer/CoinJoin transactions (obfuscation)
  - Darknet-market-like patterns (many small outputs to same destinations)
  - Round-tripping wallets (funds sent back to origin)
  - High-frequency micro-transaction spam
  - Normal traffic (baseline)
All transactions have realistic multi-input / multi-output structures.
"""

import argparse
import json
import random
import datetime
import os
import csv
import hashlib
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# ASN / GEO LOOKUP TABLE  (expanded for realism)
# ---------------------------------------------------------------------------

def generate_asn_lookup():
    return [
        # Normal / benign
        {"asn": "AS1001", "org": "Comcast",         "country": "US", "is_flagged": False},
        {"asn": "AS1002", "org": "Deutsche Telekom","country": "DE", "is_flagged": False},
        {"asn": "AS1003", "org": "NTT Japan",       "country": "JP", "is_flagged": False},
        {"asn": "AS1004", "org": "BT Group",        "country": "GB", "is_flagged": False},
        {"asn": "AS1005", "org": "Orange SA",       "country": "FR", "is_flagged": False},
        {"asn": "AS1006", "org": "Telstra",         "country": "AU", "is_flagged": False},
        {"asn": "AS1007", "org": "Rogers",          "country": "CA", "is_flagged": False},
        {"asn": "AS1008", "org": "Hetzner",         "country": "DE", "is_flagged": False},
        {"asn": "AS1009", "org": "DigitalOcean",    "country": "US", "is_flagged": False},
        {"asn": "AS1010", "org": "Linode LLC",      "country": "US", "is_flagged": False},
        # Flagged / sanctioned
        {"asn": "AS6666", "org": "Rostelecom",      "country": "RU", "is_flagged": True},
        {"asn": "AS7777", "org": "KPTC",            "country": "KP", "is_flagged": True},
        {"asn": "AS8888", "org": "TCI Iran",        "country": "IR", "is_flagged": True},
        {"asn": "AS9999", "org": "Shandong Telecom","country": "CN", "is_flagged": True},
        {"asn": "AS5555", "org": "YemenNet",        "country": "YE", "is_flagged": True},
    ]

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def random_ip(reserved_ranges=None):
    """Generate a random non-private IPv4 address."""
    while True:
        a = random.randint(1, 223)
        b = random.randint(0, 255)
        c = random.randint(0, 255)
        d = random.randint(1, 254)
        # Avoid RFC-1918 private ranges
        if a == 10:
            continue
        if a == 172 and 16 <= b <= 31:
            continue
        if a == 192 and b == 168:
            continue
        return f"{a}.{b}.{c}.{d}"


def random_wallet(prefix="1"):
    """Generate a realistic-looking base58 Bitcoin wallet address."""
    chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    length = random.randint(25, 34)
    return prefix + "".join(random.choice(chars) for _ in range(length - len(prefix)))


def deterministic_wallet(seed_str):
    """Create a deterministic wallet address from a seed string (for reproducibility)."""
    h = hashlib.sha256(seed_str.encode()).hexdigest()[:32]
    chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "1" + "".join(chars[int(h[i:i+2], 16) % len(chars)] for i in range(0, 32, 2))


def fee_for_inputs_outputs(n_in, n_out, fee_rate_sat_per_vb=None):
    """Realistic fee: ~148*n_in + 34*n_out + 10 vbytes @ fee_rate sat/vb, converted to BTC."""
    if fee_rate_sat_per_vb is None:
        fee_rate_sat_per_vb = random.randint(5, 80)  # 5–80 sat/vB is typical
    vbytes = 148 * n_in + 34 * n_out + 10
    sat = vbytes * fee_rate_sat_per_vb
    return round(sat / 1e8, 8)  # BTC


def random_utxo_amounts(total_btc, n_outputs):
    """Split total into n_outputs parts that sum to total."""
    cuts = sorted(random.uniform(0, total_btc) for _ in range(n_outputs - 1))
    parts = []
    prev = 0
    for c in cuts:
        parts.append(round(c - prev, 8))
        prev = c
    parts.append(round(total_btc - prev, 8))
    return [max(0.0001, p) for p in parts]


def script_type_for(n_in, n_out):
    weights = {"P2WPKH": 0.50, "P2PKH": 0.25, "P2SH": 0.15, "P2WSH": 0.07, "P2TR": 0.03}
    return random.choices(list(weights.keys()), weights=list(weights.values()))[0]


def make_txid(tag, idx, rand):
    return f"tx_{tag}_{idx:04d}_{rand:06x}"


# ---------------------------------------------------------------------------
# PATTERN GENERATORS
# ---------------------------------------------------------------------------

def gen_peeling_chains(asn_list, base_time, num_chains=8, hops_range=(6, 20)):
    """
    Peeling chain: 1 input → 2 outputs per hop.
    One output is the 'peel' (small amount to a fresh address),
    the other continues the chain with the remaining balance.
    Classic money-laundering fingerprint.
    """
    rows = []
    peeling_wallets = set()
    flagged_asn_wallets = set()
    asn_country = {a["asn"]: a["country"] for a in asn_list}

    for c in range(num_chains):
        n_hops = random.randint(*hops_range)
        seed = random_wallet(prefix="1Peel")
        peeling_wallets.add(seed)
        current = seed
        chain_time = base_time + datetime.timedelta(hours=c * random.randint(8, 24))
        balance = round(random.uniform(0.5, 10.0), 8)

        for h in range(n_hops):
            fee = fee_for_inputs_outputs(1, 2)
            if balance - fee < 0.0002:
                break

            # Peel fraction: 5–30 % of balance
            peel_frac = random.uniform(0.05, 0.30)
            peel_amt = round(balance * peel_frac, 8)
            continue_amt = round(balance - peel_amt - fee, 8)
            if continue_amt < 0.0001:
                break

            peel_dest = random_wallet(prefix="1D")
            next_wallet = random_wallet(prefix="1P")
            peeling_wallets.update([peel_dest, next_wallet])

            # Consistent small time-delta between hops (5–15 min)
            chain_time += datetime.timedelta(minutes=random.randint(5, 15))
            asn_obj = random.choice(asn_list)
            if asn_obj["is_flagged"]:
                flagged_asn_wallets.add(current)

            rows.append({
                "timestamp": chain_time.isoformat(),
                "src_ip": random_ip(),
                "dst_ip": random_ip(),
                "src_port": random.randint(1024, 65535),
                "dst_port": 8333,
                "txid": make_txid("peel", c * 100 + h, random.randint(0, 0xFFFFFF)),
                "input_addresses": json.dumps([current]),
                "output_addresses": json.dumps([peel_dest, next_wallet]),
                "input_amounts": json.dumps([round(balance, 8)]),
                "output_amounts": json.dumps([peel_amt, continue_amt]),
                "fee": fee,
                "script_type": "P2WPKH",
                "geo_country": asn_country[asn_obj["asn"]],
                "asn": asn_obj["asn"],
            })
            current = next_wallet
            balance = continue_amt

    return rows, peeling_wallets, flagged_asn_wallets


def gen_entity_clusters(asn_list, base_time, num_clusters=5, txns_per_cluster=40):
    """
    Entity clusters: multiple wallets co-signing the same transactions
    (co-input heuristic → belongs to same entity).
    """
    rows = []
    cluster_wallets = set()
    flagged_asn_wallets = set()
    asn_country = {a["asn"]: a["country"] for a in asn_list}
    flagged_asns = [a["asn"] for a in asn_list if a["is_flagged"]]
    normal_asns = [a["asn"] for a in asn_list if not a["is_flagged"]]

    for cl in range(num_clusters):
        # 4–10 member wallets per cluster
        n_members = random.randint(4, 10)
        members = [random_wallet(prefix=f"1E{cl}") for _ in range(n_members)]
        cluster_wallets.update(members)

        # First cluster uses flagged ASN for extra heat
        asn = random.choice(flagged_asns if cl == 0 else normal_asns)
        shared_ip = random_ip()  # same IP = same entity

        for t in range(txns_per_cluster):
            n_in = random.randint(2, min(6, n_members))
            n_out = random.randint(1, 4)
            inputs = random.sample(members, n_in)
            outputs = [random_wallet(prefix="1O") for _ in range(n_out)]
            in_amts = [round(random.uniform(0.05, 3.0), 8) for _ in inputs]
            total_in = sum(in_amts)
            fee = fee_for_inputs_outputs(n_in, n_out)
            out_amts = random_utxo_amounts(max(0.0001, total_in - fee), n_out)

            if asn in flagged_asns:
                for w in inputs:
                    flagged_asn_wallets.add(w)

            tx_time = base_time + datetime.timedelta(
                hours=random.randint(0, 120),
                minutes=random.randint(0, 59)
            )
            rows.append({
                "timestamp": tx_time.isoformat(),
                "src_ip": shared_ip,
                "dst_ip": random_ip(),
                "src_port": random.randint(1024, 65535),
                "dst_port": 8333,
                "txid": make_txid(f"cluster{cl}", t, random.randint(0, 0xFFFFFF)),
                "input_addresses": json.dumps(inputs),
                "output_addresses": json.dumps(outputs),
                "input_amounts": json.dumps(in_amts),
                "output_amounts": json.dumps(out_amts),
                "fee": fee,
                "script_type": script_type_for(n_in, n_out),
                "geo_country": asn_country[asn],
                "asn": asn,
            })

    return rows, cluster_wallets, flagged_asn_wallets


def gen_coinjoin_mixer(asn_list, base_time, n_rounds=6, participants=10):
    """
    CoinJoin mixer rounds: many participants merge into a single large tx
    with equal-value outputs (classic Wasabi/JoinMarket pattern).
    """
    rows = []
    mixer_wallets = set()
    asn_country = {a["asn"]: a["country"] for a in asn_list}

    for r in range(n_rounds):
        # All participants contribute ~0.1 BTC per round
        in_wallets = [random_wallet(prefix="1M") for _ in range(participants)]
        out_wallets = [random_wallet(prefix="1M") for _ in range(participants)]
        mixer_wallets.update(in_wallets + out_wallets)

        equal_amount = round(random.uniform(0.05, 0.5), 8)
        in_amts = [round(equal_amount + random.uniform(0, 0.005), 8) for _ in in_wallets]
        fee = fee_for_inputs_outputs(participants, participants)
        out_amts = [equal_amount] * participants  # equal outputs = mixer fingerprint

        asn_obj = random.choice(asn_list)
        tx_time = base_time + datetime.timedelta(hours=r * 4, minutes=random.randint(0, 59))

        rows.append({
            "timestamp": tx_time.isoformat(),
            "src_ip": random_ip(),
            "dst_ip": random_ip(),
            "src_port": random.randint(1024, 65535),
            "dst_port": 8333,
            "txid": make_txid("mixer", r, random.randint(0, 0xFFFFFF)),
            "input_addresses": json.dumps(in_wallets),
            "output_addresses": json.dumps(out_wallets),
            "input_amounts": json.dumps(in_amts),
            "output_amounts": json.dumps(out_amts),
            "fee": fee,
            "script_type": "P2WSH",
            "geo_country": asn_country[asn_obj["asn"]],
            "asn": asn_obj["asn"],
        })

    return rows, mixer_wallets


def gen_darknet_market(asn_list, base_time, n_orders=60):
    """
    Darknet market pattern: many small payments from different buyers
    to a handful of vendor wallets, routed through flagged ASNs.
    """
    rows = []
    market_wallets = set()
    flagged_asn_wallets = set()
    asn_country = {a["asn"]: a["country"] for a in asn_list}
    flagged_asns = [a["asn"] for a in asn_list if a["is_flagged"]]

    vendors = [random_wallet(prefix="1V") for _ in range(5)]
    market_wallets.update(vendors)

    for i in range(n_orders):
        buyer = random_wallet(prefix="1B")
        market_wallets.add(buyer)
        vendor = random.choice(vendors)
        amount = round(random.uniform(0.001, 0.05), 8)  # small payments
        fee = fee_for_inputs_outputs(1, 2)
        change = round(random.uniform(0.0001, 0.01), 8)

        asn = random.choice(flagged_asns)  # darknet uses flagged ASN
        flagged_asn_wallets.update([buyer, vendor])

        tx_time = base_time + datetime.timedelta(
            hours=random.randint(0, 168),
            minutes=random.randint(0, 59)
        )
        rows.append({
            "timestamp": tx_time.isoformat(),
            "src_ip": random_ip(),
            "dst_ip": random_ip(),
            "src_port": random.randint(1024, 65535),
            "dst_port": 8333,
            "txid": make_txid("dnm", i, random.randint(0, 0xFFFFFF)),
            "input_addresses": json.dumps([buyer]),
            "output_addresses": json.dumps([vendor, buyer]),  # vendor + change back
            "input_amounts": json.dumps([round(amount + change + fee, 8)]),
            "output_amounts": json.dumps([amount, change]),
            "fee": fee,
            "script_type": "P2PKH",
            "geo_country": asn_country[asn],
            "asn": asn,
        })

    return rows, market_wallets, flagged_asn_wallets


def gen_round_trip(asn_list, base_time, n_trips=20):
    """
    Round-tripping: funds sent from A→B then B→A to simulate normal activity.
    Often used to obscure illicit flow.
    """
    rows = []
    trip_wallets = set()
    asn_country = {a["asn"]: a["country"] for a in asn_list}

    for i in range(n_trips):
        wallet_a = random_wallet(prefix="1R")
        wallet_b = random_wallet(prefix="1R")
        trip_wallets.update([wallet_a, wallet_b])

        amount_ab = round(random.uniform(0.1, 2.0), 8)
        fee1 = fee_for_inputs_outputs(1, 2)
        fee2 = fee_for_inputs_outputs(1, 2)
        change1 = round(random.uniform(0.001, 0.05), 8)
        change2 = round(random.uniform(0.001, 0.05), 8)

        asn_obj = random.choice(asn_list)
        t1 = base_time + datetime.timedelta(hours=random.randint(1, 100))
        t2 = t1 + datetime.timedelta(minutes=random.randint(30, 120))

        # A → B
        rows.append({
            "timestamp": t1.isoformat(),
            "src_ip": random_ip(),
            "dst_ip": random_ip(),
            "src_port": random.randint(1024, 65535),
            "dst_port": 8333,
            "txid": make_txid("trip_ab", i, random.randint(0, 0xFFFFFF)),
            "input_addresses": json.dumps([wallet_a]),
            "output_addresses": json.dumps([wallet_b, wallet_a]),
            "input_amounts": json.dumps([round(amount_ab + change1 + fee1, 8)]),
            "output_amounts": json.dumps([amount_ab, change1]),
            "fee": fee1,
            "script_type": script_type_for(1, 2),
            "geo_country": asn_country[asn_obj["asn"]],
            "asn": asn_obj["asn"],
        })
        # B → A (return)
        rows.append({
            "timestamp": t2.isoformat(),
            "src_ip": random_ip(),
            "dst_ip": random_ip(),
            "src_port": random.randint(1024, 65535),
            "dst_port": 8333,
            "txid": make_txid("trip_ba", i, random.randint(0, 0xFFFFFF)),
            "input_addresses": json.dumps([wallet_b]),
            "output_addresses": json.dumps([wallet_a, wallet_b]),
            "input_amounts": json.dumps([round(amount_ab - fee2 + change2, 8)]),
            "output_amounts": json.dumps([round(amount_ab - fee2, 8), change2]),
            "fee": fee2,
            "script_type": script_type_for(1, 2),
            "geo_country": asn_country[asn_obj["asn"]],
            "asn": asn_obj["asn"],
        })

    return rows, trip_wallets


def gen_normal_traffic(asn_list, base_time, n_rows=700):
    """
    Normal baseline traffic: varied inputs (1–4), outputs (1–5),
    random amounts, mix of script types, mostly non-flagged ASNs.
    """
    rows = []
    flagged_asn_wallets = set()
    asn_country = {a["asn"]: a["country"] for a in asn_list}
    flagged_asns = [a["asn"] for a in asn_list if a["is_flagged"]]
    normal_asns = [a["asn"] for a in asn_list if not a["is_flagged"]]

    for i in range(n_rows):
        n_in = random.randint(1, 4)
        n_out = random.randint(1, 5)
        inputs = [random_wallet(prefix="1N") for _ in range(n_in)]
        outputs = [random_wallet(prefix="1N") for _ in range(n_out)]
        in_amts = [round(random.uniform(0.001, 5.0), 8) for _ in inputs]
        total_in = sum(in_amts)
        fee = fee_for_inputs_outputs(n_in, n_out)
        out_amts = random_utxo_amounts(max(0.0001, total_in - fee), n_out)

        # 5% chance of flagged ASN in normal traffic
        asn = random.choice(flagged_asns if random.random() < 0.05 else normal_asns)
        if asn in flagged_asns:
            for w in inputs:
                flagged_asn_wallets.add(w)

        tx_time = base_time + datetime.timedelta(minutes=random.randint(0, 10080))

        rows.append({
            "timestamp": tx_time.isoformat(),
            "src_ip": random_ip(),
            "dst_ip": random_ip(),
            "src_port": random.randint(1024, 65535),
            "dst_port": 8333,
            "txid": make_txid("norm", i, random.randint(0, 0xFFFFFF)),
            "input_addresses": json.dumps(inputs),
            "output_addresses": json.dumps(outputs),
            "input_amounts": json.dumps(in_amts),
            "output_amounts": json.dumps(out_amts),
            "fee": fee,
            "script_type": script_type_for(n_in, n_out),
            "geo_country": asn_country[asn],
            "asn": asn,
        })

    return rows, flagged_asn_wallets


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------

def generate_dataset(num_rows=2000, output_dir="data_gen/sample_output"):
    os.makedirs(output_dir, exist_ok=True)

    asn_list = generate_asn_lookup()

    # Save ASN lookup CSV
    asn_csv = os.path.join(output_dir, "asn_lookup.csv")
    with open(asn_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["asn", "org", "country", "is_flagged"])
        writer.writeheader()
        writer.writerows(asn_list)

    base_time = datetime.datetime.utcnow() - datetime.timedelta(days=14)

    all_rows = []
    all_peeling_wallets = set()
    all_cluster_wallets = set()
    all_flagged_asn_wallets = set()
    all_mixer_wallets = set()

    # --- Peeling chains (~15% of rows) ---
    n_chains = max(5, int(num_rows * 0.15 // 12))
    peel_rows, pw, faw1 = gen_peeling_chains(asn_list, base_time, num_chains=n_chains, hops_range=(6, 15))
    all_rows.extend(peel_rows)
    all_peeling_wallets.update(pw)
    all_flagged_asn_wallets.update(faw1)

    # --- Entity clusters (~15% of rows) ---
    n_clusters = max(4, int(num_rows * 0.15 // 40))
    cluster_rows, cw, faw2 = gen_entity_clusters(asn_list, base_time, num_clusters=n_clusters, txns_per_cluster=40)
    all_rows.extend(cluster_rows)
    all_cluster_wallets.update(cw)
    all_flagged_asn_wallets.update(faw2)

    # --- CoinJoin mixer (~5% of rows) ---
    mixer_rows, mw = gen_coinjoin_mixer(asn_list, base_time, n_rounds=8, participants=10)
    all_rows.extend(mixer_rows)
    all_mixer_wallets.update(mw)

    # --- Darknet market (~8% of rows) ---
    dnm_n = max(30, int(num_rows * 0.08))
    dnm_rows, dw, faw3 = gen_darknet_market(asn_list, base_time, n_orders=dnm_n)
    all_rows.extend(dnm_rows)
    all_flagged_asn_wallets.update(faw3)

    # --- Round-tripping (~4% of rows) ---
    trip_rows, _ = gen_round_trip(asn_list, base_time, n_trips=max(15, int(num_rows * 0.02)))
    all_rows.extend(trip_rows)

    # --- Normal traffic (remaining rows) ---
    remaining = max(200, num_rows - len(all_rows))
    norm_rows, faw4 = gen_normal_traffic(asn_list, base_time, n_rows=remaining)
    all_rows.extend(norm_rows)
    all_flagged_asn_wallets.update(faw4)

    random.shuffle(all_rows)

    # ---- Save CSV ----
    csv_path = os.path.join(output_dir, "transactions.csv")
    fieldnames = list(all_rows[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    # ---- Save JSON ----
    json_path = os.path.join(output_dir, "transactions.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2)

    # ---- Save XML ----
    xml_path = os.path.join(output_dir, "transactions.xml")
    root_elem = ET.Element("transactions")
    for r in all_rows:
        tx_elem = ET.SubElement(root_elem, "transaction")
        for k, v in r.items():
            child = ET.SubElement(tx_elem, k)
            child.text = str(v)
    ET.ElementTree(root_elem).write(xml_path, encoding="utf-8", xml_declaration=True)

    # ---- Save Ground-truth Labels ----
    labels = {
        "peeling_wallets":    sorted(all_peeling_wallets),
        "cluster_wallets":    sorted(all_cluster_wallets),
        "mixer_wallets":      sorted(all_mixer_wallets),
        "flagged_asn_wallets": sorted(all_flagged_asn_wallets),
    }
    with open(os.path.join(output_dir, "labels.json"), "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2)

    print(f"\n✓ Generated {len(all_rows)} transactions → {output_dir}")
    print(f"  Peeling chain wallets : {len(all_peeling_wallets)}")
    print(f"  Entity cluster wallets: {len(all_cluster_wallets)}")
    print(f"  Mixer wallets         : {len(all_mixer_wallets)}")
    print(f"  Flagged ASN wallets   : {len(all_flagged_asn_wallets)}")
    print(f"  Pattern breakdown:")
    print(f"    Peeling   : {len(peel_rows)}")
    print(f"    Cluster   : {len(cluster_rows)}")
    print(f"    Mixer     : {len(mixer_rows)}")
    print(f"    Darknet   : {len(dnm_rows)}")
    print(f"    RoundTrip : {len(trip_rows)}")
    print(f"    Normal    : {len(norm_rows)}")

    return labels


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TNF-CL Enhanced Bitcoin+Network Dataset Generator")
    parser.add_argument("--rows",   type=int, default=2000,                    help="Target number of transaction rows")
    parser.add_argument("--output", type=str, default="data_gen/sample_output", help="Output directory")
    args = parser.parse_args()
    generate_dataset(num_rows=args.rows, output_dir=args.output)
