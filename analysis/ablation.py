"""
Ablation Study Runner — configure top section, then: python ablation.py
  -t time|mem        target to predict (overrides DATA)
  -m lreg lsvm ...  models to run (default: all)

Results -> ablation_results/<timestamp>/results.json + run.log
"""

# ── Configuration ─────────────────────────────────────────────────────────────

DATA = {
    "path":                    "training_data/rdbms_training_data.parquet",
    "rename":                  {"min_cut_upper": "min_cut"},
    "target":                  "best_mem_method",   # or "best_time_method"
    "test_size":               0.2,
    "random_state":            42,
    "drop_columns_containing": ["statevector_saved_e", "statevector_saved_m"],
}

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

FEATURE_SETS = {
    "SQL":                            SQL,
    "Static":                         STATIC,
    "Static + Graph":                 STATIC + GRAPH,
    "Static + SQL":                   STATIC + SQL,
    "Static + Dynamic":               STATIC + DYNAMIC,
    "Static + Graph + SQL":           STATIC + GRAPH + SQL,
    "Static + Graph + SQL + Dynamic": STATIC + GRAPH + SQL + DYNAMIC,
}

RDBMS_METHODS  = ["sqlite", "ducksql", "psql"]
QISKIT_METHODS = ["density_matrix", "matrix_product_state",
                  "extended_stabilizer", "statevector"]

# ── Models ────────────────────────────────────────────────────────────────────

from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC, SVC
from sklearn.tree import DecisionTreeClassifier
from xgboost import XGBClassifier

from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC

MODELS = {
    # "knn":  lambda: make_pipeline(StandardScaler(), KNeighborsClassifier(7)),
    "lreg": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced")),
    "lsvm": lambda: make_pipeline(StandardScaler(), CalibratedClassifierCV(SVC(kernel="linear", class_weight="balanced"), cv=3)),
    "dect": lambda: DecisionTreeClassifier(class_weight="balanced", random_state=42),
    "rf":   lambda: RandomForestClassifier(300, n_jobs=-1, class_weight="balanced", random_state=42),
    "xgb":  lambda: XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.1,
                                   subsample=0.8, colsample_bytree=0.8,
                                   objective="binary:logistic", eval_metric="logloss",
                                   random_state=42),
}

# ── Boilerplate ───────────────────────────────────────────────────────────────

import io, json, logging, pathlib, sys, time
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_class_weight

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out_dir   = pathlib.Path("ablation_results") / timestamp
out_dir.mkdir(parents=True, exist_ok=True)
split_dir = pathlib.Path("ablation_results") / "splits"
split_dir.mkdir(parents=True, exist_ok=True)

_fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
_fh  = logging.FileHandler(out_dir / "run.log", encoding="utf-8")
_sh  = logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True))
for h in (_fh, _sh): h.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _sh])
log = logging.getLogger(__name__)

def _bar(done, total, w=28):
    n = int(w * done / total)
    return f"[{'#'*n}{'.'*(w-n)}] {done}/{total}"

def _hms(s):
    s = int(s); h, r = divmod(s, 3600); m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def _sep(c="=", w=64): log.info(c * w)

# ── Data ──────────────────────────────────────────────────────────────────────

def load_data(cfg):
    df = pd.read_parquet(cfg["path"])
    df.rename(columns=cfg.get("rename", {}), inplace=True)
    for s in cfg.get("drop_columns_containing", []):
        df.drop(columns=[c for c in df.columns if s in c], inplace=True)
    return df

def build_target(df, cfg):
    all_m = RDBMS_METHODS + QISKIT_METHODS
    tcols = [c for m in all_m for c in df.columns if m in c and c.endswith(("time_s", "execution_time"))]
    mcols = [c for m in all_m for c in df.columns if m in c and c.endswith(("memory_usage", "mb"))]
    def best(pool):
        return pd.DataFrame({m: df[[c for c in pool if m in c]].min(axis=1) for m in all_m
                             if any(m in c for c in pool)}).idxmin(axis=1)
    df["best_time_method"] = best(tcols)
    df["best_mem_method"]  = best(mcols)
    for col in ("best_time_method", "best_mem_method"):
        df[col] = df[col].apply(lambda m: "RDBMS" if m in RDBMS_METHODS else "QISKIT")
    return df[cfg["target"]]

def evaluate(model, X_test, y_test):
    probs = model.predict_proba(X_test)[:, 1]
    preds = (probs > 0.5).astype(int)
    return {"accuracy": round(accuracy_score(y_test, preds), 4),
            "f1":       round(f1_score(y_test, preds),       4),
            "roc_auc":  round(roc_auc_score(y_test, probs),  4)}

# ── Main ──────────────────────────────────────────────────────────────────────

def run_ablation():
    t_run = time.time()
    _sep("=")
    log.info("  ABLATION STUDY  |  target: %s  |  models: %s", DATA["target"], ", ".join(MODELS))
    log.info("  %d feature sets x %d models = %d runs  ->  %s", len(FEATURE_SETS), len(MODELS),
             len(FEATURE_SETS) * len(MODELS), out_dir)
    _sep("=")

    log.info(">> Loading %s ...", DATA["path"])
    t0 = time.time(); df = load_data(DATA)
    log.info("   %d rows x %d cols  (%.1fs)", len(df), len(df.columns), time.time() - t0)

    log.info(">> Building target: %s ...", DATA["target"])
    t0 = time.time(); y = LabelEncoder().fit_transform(build_target(df, DATA))
    counts = dict(zip(*np.unique(y, return_counts=True)))
    log.info("   %s  (%.1fs)", "  |  ".join(f"class {k} = {v} ({100*v/len(y):.1f}%)"
             for k, v in counts.items()), time.time() - t0)

    split_file = split_dir / f"split_{len(df)}_{DATA['random_state']}.npz"
    if split_file.exists():
        z = np.load(split_file); train_idx, test_idx = z["train"], z["test"]
        log.info(">> Cached split loaded  (train=%d  test=%d)", len(train_idx), len(test_idx))
    else:
        train_idx, test_idx = train_test_split(np.arange(len(df)), test_size=DATA["test_size"],
                                               random_state=DATA["random_state"], stratify=y)
        np.savez(split_file, train=train_idx, test=test_idx)
        log.info(">> Split created  (train=%d  test=%d)  -> saved", len(train_idx), len(test_idx))

    cw = compute_class_weight("balanced", classes=np.unique(y[train_idx]), y=y[train_idx])
    sw = np.array([cw[c] for c in y[train_idx]])

    results, n = [], 0
    for name, fn in MODELS.items():
        t_model = time.time(); _sep("-"); log.info("  MODEL: %s", name); _sep("-")
        for fs_name, feats in FEATURE_SETS.items():
            n += 1
            cols = [c for c in feats if c in df.columns]
            log.info("%s  %s  (%d features)", _bar(n, len(MODELS) * len(FEATURE_SETS)), fs_name, len(cols))

            m = fn()
            from sklearn.pipeline import Pipeline
            fit_params = ({f"{m.steps[-1][0]}__sample_weight": sw} if isinstance(m, Pipeline)
                          else {"sample_weight": sw})

            t0 = time.time()
            m.fit(df.iloc[train_idx][cols], y[train_idx], **fit_params)
            train_time_s = round(time.time() - t0, 2)

            t0 = time.time()
            metrics = evaluate(m, df.iloc[test_idx][cols], y[test_idx])
            infer_time_s = round(time.time() - t0, 4)

            results.append({"model": name, "features": fs_name, "n_features": len(cols),
                            "train_time_s": train_time_s, "infer_time_s": infer_time_s, **metrics})
            log.info("      acc=%.4f  f1=%.4f  auc=%.4f  train=%.2fs  infer=%.4fs",
                     metrics["accuracy"], metrics["f1"], metrics["roc_auc"], train_time_s, infer_time_s)
        log.info("   Done: %s  (%.1fs)", name, time.time() - t_model)

    _sep("="); log.info("  RESULTS  (sorted by F1)"); _sep("-")
    log.info("  %-36s  %-6s  %6s  %6s  %6s  %9s  %10s",
             "Feature Set", "Model", "Acc", "F1", "AUC", "Train(s)", "Infer(s)"); _sep("-")
    for r in sorted(results, key=lambda x: x["f1"], reverse=True):
        log.info("  %-36s  %-6s  %.4f  %.4f  %.4f  %9.2f  %10.4f",
                 r["features"], r["model"], r["accuracy"], r["f1"], r["roc_auc"],
                 r["train_time_s"], r["infer_time_s"])

    (out_dir / "results.json").write_text(json.dumps({
        "timestamp": timestamp, "target": DATA["target"], "test_size": DATA["test_size"],
        "n_samples": len(df), "total_time_s": round(time.time() - t_run, 2),
        "results": sorted(results, key=lambda r: r["f1"], reverse=True),
    }, indent=2), encoding="utf-8")

    _sep("=")
    log.info("  Done in %s  |  %s", _hms(time.time() - t_run), out_dir)
    _sep("=")

# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    TARGETS = {"time": "best_time_method", "mem": "best_mem_method"}
    parser  = argparse.ArgumentParser(description="Ablation Study Runner")
    parser.add_argument("-m", "--models", nargs="+", metavar="MODEL",
                        help=f"Models to run (default: all). Choices: {list(MODELS)}")
    parser.add_argument("-t", "--target", choices=TARGETS,
                        help="Target: 'time' or 'mem' (overrides DATA['target'])")
    args = parser.parse_args()

    if args.models:
        bad = [m for m in args.models if m not in MODELS]
        if bad: parser.error(f"Unknown model(s): {bad}. Available: {list(MODELS)}")
        MODELS = {k: v for k, v in MODELS.items() if k in args.models}

    if args.target:
        DATA["target"] = TARGETS[args.target]

    run_ablation()