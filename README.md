# TNF-CL — Temporal Network-Fusion Cross-attention Ledger

**AI-Powered Monitoring & Analysis of Bitcoin Transaction Traffic**  
*Smart India Hackathon Problem Statement 26146 (NTRO)*

---

## 📌 Executive Summary

Bitcoin transactions are pseudonymous:
- **Blockchain layer** captures wallet-to-wallet coin movements, output amounts, transaction fees, and script types.
- **Network layer** captures IP addresses, ports, timestamps, ASNs, and geographical locations.

**TNF-CL** correlates network-layer metadata with blockchain-layer transactions using a **heterogeneous graph structure** ($IP \leftrightarrow Wallet \leftrightarrow TXID$) and a **cross-attention feature fusion model**. It scores and ranks high-risk wallets/transactions while delivering **plain-language explainability** for law enforcement and intelligence analysts.

---

## 🏗 System Architecture & Workflow

```
┌───────────────────────────┐     ┌───────────────────────────┐
│   Network-Layer Events    │     │  Blockchain-Layer Txns    │
│  (IP, Port, Time, ASN)    │     │  (Wallet, TXID, Amounts)  │
└─────────────┬─────────────┘     └─────────────┬─────────────┘
              │                                 │
              └────────────────┬────────────────┘
                               ▼
            ┌──────────────────────────────────────┐
            │   Correlation Engine & SQLite Storage│
            └──────────────────┬───────────────────┘
                               ▼
            ┌──────────────────────────────────────┐
            │ Heterogeneous Graph Construction     │
            │      (IP ↔ Wallet ↔ TXID)            │
            └──────────────────┬───────────────────┘
                               ▼
            ┌──────────────────────────────────────┐
            │     AI/ML Detection & Fusion         │
            │ 1. Entity Clustering (Co-Input)      │
            │ 2. IsolationForest Anomaly Score     │
            │ 3. Peeling Chain Detector            │
            │ 4. PageRank Proximity & Cross-Attn   │
            └──────────────────┬───────────────────┘
                               ▼
            ┌──────────────────────────────────────┐
            │   Explainable Risk Scoring (0–100)   │
            └──────────────────┬───────────────────┘
                               ▼
            ┌──────────────────────────────────────┐
            │   FastAPI Backend + React/HTML Dashboard│
            └──────────────────────────────────────┘
```

---

## 🚀 Key Features & Detection Modules

### 1. Multi-Format Ingestion & Correlation
- Supports **CSV, JSON, and XML** data feeds.
- Enriches network events with offline GeoIP/ASN tables (`asn, country, is_flagged`).
- Joins network events to blockchain transactions on `TXID` and nearest timestamps.

### 2. Heterogeneous Graph Construction
- Constructs a directed graph in NetworkX with node types `IP`, `Wallet`, and `TXID`.
- Edges:
  - `Wallet` $\rightarrow$ `TXID` (`sent_from`)
  - `TXID` $\rightarrow$ `Wallet` (`received_by`)
  - `IP` $\rightarrow$ `TXID` (`observed_via`)
- Fast 2-hop neighborhood extraction API (`/graph/{node_id}`).

### 3. AI/ML Detection Engine
- **Entity Clustering**: Groups wallets controlled by the same operator using the **Common-Input-Ownership** heuristic.
- **Anomaly Detection**: `IsolationForest` unsupervised model trained on transaction frequency, amount variance, and in/out volume ratios.
- **Peeling Chain Detector**: Identifies peeling chains ($1 \text{ input} \rightarrow 2 \text{ outputs}$ with repeated peel patterns over $\ge 3$ hops).
- **TNF-CL Cross-Attention Fusion**: Fuses 4-dimensional network embeddings with 4-dimensional blockchain embeddings using dot-product/Multihead Attention.

### 4. Explainable Risk Scoring Engine
Calculates a transparent, weighted risk score (capped at 100) per wallet:
- **Flagged ASN Hit**: $+20.0$ points
- **Peeling-Chain Pattern**: $+30.0$ points
- **IsolationForest Anomaly**: Up to $+25.0$ points
- **PageRank Graph Proximity**: Up to $+25.0$ points

Each flagged wallet includes plain-language evidence lines (e.g., `"Flagged ASN AS6666 detected → +20"`).

---

## 🛠 Quickstart Guide (100% Offline)

### Prerequisites
- Python 3.9+
- Dependencies installed via `pip install -r requirements.txt`

### One-Command Execution

**On Linux/macOS:**
```bash
chmod +x run_demo.sh
./run_demo.sh
```

**On Windows:**
```cmd
run_demo.bat
```

Open your browser at: **`http://localhost:8000`**

---

## 📡 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/ingest` | Ingests dataset, builds graph, and runs AI detection |
| `GET`  | `/stats`  | Overall summary counts and risk band distribution |
| `GET`  | `/alerts` | Ranked list of suspicious wallets with top reasons |
| `GET`  | `/wallet/{id}` | Full wallet detail, connected IPs, and risk breakdown |
| `GET`  | `/graph/{id}`  | Graph neighborhood nodes and links JSON |

---

## 📁 Repository Structure

```
├── backend/
│   ├── database.py       # SQLite connection and table definitions
│   ├── detectors.py      # ML models, peeling detection, and risk scoring
│   ├── graph.py          # NetworkX heterogeneous graph builder
│   ├── ingest.py         # CSV/JSON/XML loader and correlation engine
│   └── main.py           # FastAPI application and routes
├── data_gen/
│   ├── generate_dataset.py  # Synthetic data generator with ground truth labels
│   └── sample_output/       # Generated sample transactions and labels.json
├── frontend/
│   └── index.html        # Single-page dashboard (Overview, Alerts, Detail, Graph)
├── models/
│   └── cross_attention.py # PyTorch/NumPy cross-attention fusion module
├── README.md             # Project documentation
├── requirements.txt      # Python dependencies
├── run_demo.bat          # Windows launcher script
└── run_demo.sh           # Linux/macOS launcher script
```
