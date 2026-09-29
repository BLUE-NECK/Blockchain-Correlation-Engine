#!/bin/bash
echo "=========================================================="
echo " Starting TNF-CL Bitcoin & Network Correlation Engine Demo"
echo "=========================================================="

echo "[1/3] Generating synthetic cross-layer dataset..."
python data_gen/generate_dataset.py --rows 1000 --output data_gen/sample_output

echo "[2/3] Running ingestion, graph construction, and AI detection..."
python -c "from backend.ingest import process_and_ingest; from backend.graph import build_heterogeneous_graph; from backend.detectors import run_ml_pipeline; process_and_ingest('data_gen/sample_output/transactions.csv'); build_heterogeneous_graph(); run_ml_pipeline()"

echo "[3/3] Launching FastAPI backend server & dashboard..."
echo "Dashboard reachable at: http://localhost:8000"
uvicorn backend.main:app --host 0.0.0.0 --port 8000
