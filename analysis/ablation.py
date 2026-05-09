"""
Ablation Study Runner
=====================
Configure FEATURE_SETS, MODELS, and DATA below, then run:
    python ablation.py
Results are saved to ablation_results/<timestamp>/ as JSON + log.
"""

# ── Configuration ─────────────────────────────────────────────────────────────

DATA = {
    "path":                    "training_data/rdbms_training_data.parquet",
    "rename":                  {"min_cut_upper": "min_cut"},
    "target":                  "best_mem_method",   # or "best_mem_method"
    "test_size":               0.2,
    "random_state":            42,
    "drop_columns_containing": ["statevector_saved_e", "statevector_saved_m"],
}

# Feature groups CORE engineered in INFERQ
SQL    = ["num_joins", "num_and_clauses", "num_select_columns",
          "num_agg_funcs", "num_where_clauses", "num_eq_predicates"]
GRAPH  = ["edge_count", "max_degree", "min_cut", "diameter", "radius",
          "average_degree", "average_clustering_coefficient",
          "average_shortest_path_length", "central_point_of_dominance",
          "std_dev_adjacency_matrix"]
STATIC = ["num_qubits", "width", "depth", "circuit_size", "pauli_gate_count",
          "two_qubit_gate_count", "two_qubit_gate_percentage",
          "locality_ratio", "idling_score", "density_score"]
DYNAMIC = ["statevector_saved_sparsity", "statevector_saved_shannon_entropy"]

# Feature sets to ablate  (label -> feature list)
FEATURE_SETS = {
    "SQL":                            SQL,
    "Static":                         STATIC,
    "Static + Graph":                 STATIC + GRAPH,
    "Static + SQL":                   STATIC + SQL,
    "Static + Dynamic":               STATIC + DYNAMIC,
    "Static + Graph + SQL":           STATIC + GRAPH + SQL,
    "Static + Graph + SQL + Dynamic": STATIC + GRAPH + SQL + DYNAMIC,
}

# Method groups for binary target construction
RDBMS_METHODS  = ["sqlite", "ducksql", "psql"]
QISKIT_METHODS = ["density_matrix", "matrix_product_state",
                  "extended_stabilizer", "statevector"]

# Models to evaluate  (label -> factory callable)
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier

MODELS = {
    "XGBoost": lambda: XGBClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.1,
        subsample=0.8, colsample_bytree=0.8,
        objective="binary:logistic", eval_metric="logloss",
        random_state=42, n_jobs=-1,
    ),
    # "RandomForest": lambda: RandomForestClassifier(
    #     n_estimators=300, max_depth=10, random_state=42, n_jobs=-1,
    # ),
}

# ── Boilerplate (no need to edit below) ───────────────────────────────────────

import io, json, logging, pathlib, sys, time
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_class_weight

# Directories
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out_dir   = pathlib.Path("ablation_results") / timestamp
out_dir.mkdir(parents=True, exist_ok=True)
split_dir = pathlib.Path("ablation_results") / "splits"
split_dir.mkdir(parents=True, exist_ok=True)

log_path  = out_dir / "run.log"
json_path = out_dir / "results.json"

# Logging — force UTF-8 on both handlers so Unicode works on Windows (CP-1252) too
_fmt      = logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
_file_h   = logging.FileHandler(log_path, encoding="utf-8")
_stream_h = logging.StreamHandler(
    io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True)
)
for h in (_file_h, _stream_h):
    h.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_file_h, _stream_h])
log = logging.getLogger(__name__)

# Tiny helpers
def _bar(done, total, width=28):
    n = int(width * done / total)
    return f"[{'#' * n}{'.' * (width - n)}] {done}/{total}"

def _hms(s):
    s = int(s); h, r = divmod(s, 3600); m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def _sep(char="=", width=64):
    log.info(char * width)


# ── Data helpers ──────────────────────────────────────────────────────────────

def load_data(cfg):
    df = pd.read_parquet(cfg["path"])
    df.rename(columns=cfg.get("rename", {}), inplace=True)
    for s in cfg.get("drop_columns_containing", []):
        df.drop(columns=[c for c in df.columns if s in c], inplace=True)
    return df


def build_target(df, cfg):
    all_methods = RDBMS_METHODS + QISKIT_METHODS
    timecols, memcols = [], []
    for m in all_methods:
        timecols += [c for c in df.columns if m in c and c.endswith(("time_s", "execution_time"))]
        memcols  += [c for c in df.columns if m in c and c.endswith(("memory_usage", "mb"))]

    def best(cols_by_method):
        frame = pd.DataFrame({m: df[cols].min(axis=1)
                              for m, cols in cols_by_method.items() if cols})
        return frame.idxmin(axis=1)

    df["best_time_method"] = best({m: [c for c in timecols if m in c] for m in all_methods})
    df["best_mem_method"]  = best({m: [c for c in memcols  if m in c] for m in all_methods})
    for col in ("best_time_method", "best_mem_method"):
        df[col] = df[col].apply(lambda m: "RDBMS" if m in RDBMS_METHODS else "QISKIT")
    return df[cfg["target"]]


def evaluate(model, X_test, y_test):
    probs = model.predict_proba(X_test)[:, 1]
    preds = (probs > 0.5).astype(int)
    return {
        "accuracy": round(accuracy_score(y_test, preds), 4),
        "f1":       round(f1_score(y_test, preds),       4),
        "roc_auc":  round(roc_auc_score(y_test, probs),  4),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def run_ablation():
    run_start  = time.time()
    total_runs = len(MODELS) * len(FEATURE_SETS)

    _sep("=")
    log.info("  ABLATION STUDY")
    log.info("  Target  : %s", DATA["target"])
    log.info("  Models  : %s", ", ".join(MODELS))
    log.info("  Runs    : %d sets x %d models = %d total", len(FEATURE_SETS), len(MODELS), total_runs)
    log.info("  Output  : %s", out_dir)
    _sep("=")

    # Load
    log.info(">> Loading data from %s ...", DATA["path"])
    t0 = time.time()
    df = load_data(DATA)
    log.info("   Loaded %d rows x %d columns  (%.1fs)", len(df), len(df.columns), time.time() - t0)

    # Target
    log.info(">> Building target: %s ...", DATA["target"])
    t0    = time.time()
    y_raw = build_target(df, DATA)
    le    = LabelEncoder()
    y     = le.fit_transform(y_raw)
    counts = dict(zip(*np.unique(y, return_counts=True)))
    log.info("   Classes: %s  (%.1fs)",
             "  |  ".join(f"{le.classes_[k]} = {v} ({100*v/len(y):.1f}%)" for k, v in counts.items()),
             time.time() - t0)

    # Split
    split_file = split_dir / f"split_{len(df)}_{DATA['random_state']}.npz"
    if split_file.exists():
        z = np.load(split_file)
        train_idx, test_idx = z["train"], z["test"]
        log.info(">> Loaded cached split  (train=%d  test=%d)", len(train_idx), len(test_idx))
    else:
        train_idx, test_idx = train_test_split(
            np.arange(len(df)), test_size=DATA["test_size"],
            random_state=DATA["random_state"], stratify=y,
        )
        np.savez(split_file, train=train_idx, test=test_idx)
        log.info(">> Created split  (train=%d  test=%d)  -> saved", len(train_idx), len(test_idx))

    cw = compute_class_weight("balanced", classes=np.unique(y[train_idx]), y=y[train_idx])
    sample_weights = np.array([cw[c] for c in y[train_idx]])

    # Ablation loop
    all_results, run_num = [], 0

    for model_name, model_fn in MODELS.items():
        model_start = time.time()
        _sep("-")
        log.info("  MODEL: %s", model_name)
        _sep("-")

        for fs_name, features in FEATURE_SETS.items():
            run_num += 1
            cols    = [c for c in features if c in df.columns]
            if missing := set(features) - set(cols):
                log.warning("  [!] Missing features skipped: %s", missing)

            log.info("%s  %s  (%d features)", _bar(run_num, total_runs), fs_name, len(cols))

            t0    = time.time()
            model = model_fn()
            model.fit(df.iloc[train_idx][cols], y[train_idx], sample_weight=sample_weights)
            train_time = time.time() - t0

            metrics = evaluate(model, df.iloc[test_idx][cols], y[test_idx])
            all_results.append({"model": model_name, "features": fs_name,
                                 "n_features": len(cols), "train_time_s": round(train_time, 2),
                                 **metrics})

            log.info("      acc=%.4f  f1=%.4f  auc=%.4f  (%.1fs)",
                     metrics["accuracy"], metrics["f1"], metrics["roc_auc"], train_time)

        log.info("   Done: %s  (%.1fs total)", model_name, time.time() - model_start)

    # Summary table
    _sep("=")
    log.info("  RESULTS  (sorted by F1)")
    _sep("-")
    log.info("  %-36s  %-14s  %6s  %6s  %6s", "Feature Set", "Model", "Acc", "F1", "AUC")
    _sep("-")
    for r in sorted(all_results, key=lambda x: x["f1"], reverse=True):
        log.info("  %-36s  %-14s  %.4f  %.4f  %.4f",
                 r["features"], r["model"], r["accuracy"], r["f1"], r["roc_auc"])

    # Save JSON
    json_path.write_text(json.dumps({
        "timestamp":    timestamp,
        "target":       DATA["target"],
        "test_size":    DATA["test_size"],
        "n_samples":    len(df),
        "total_time_s": round(time.time() - run_start, 2),
        "results":      sorted(all_results, key=lambda r: r["f1"], reverse=True),
    }, indent=2), encoding="utf-8")

    _sep("=")
    log.info("  Finished in %s", _hms(time.time() - run_start))
    log.info("  JSON -> %s", json_path)
    log.info("  Log  -> %s", log_path)
    _sep("=")


if __name__ == "__main__":
    run_ablation()