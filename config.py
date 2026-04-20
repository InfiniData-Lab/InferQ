"""
Quantum Circuit Pipeline Configuration
Centralized configuration for all pipeline components
"""

import os
import multiprocessing as mp
from pathlib import Path


class PipelineConfig:
    """Central configuration for the quantum circuit pipeline."""

    def __init__(self):
        # Base paths
        self.project_root = Path(__file__).parent
        self.circuits_dir = self.project_root / "circuits"
        self.logs_dir = self.project_root / "logs"

        # Ensure directories exist
        self.circuits_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)

    # System Configuration
    @property
    def cpu_cores(self):
        """Available CPU cores."""
        return mp.cpu_count()

    @property
    def optimal_workers(self):
        """Optimal number of worker processes."""
        return max(1, self.cpu_cores - 2)

    # Pipeline Defaults
    PIPELINE_DEFAULTS = {
        "workers": 5,  # Auto-detect
        "batch_size": 10,
        "azure_upload_interval": 10,
        "max_iterations": None,  # Infinite
        "batch_timeout_seconds": 200,  # 5 minutes timeout per worker task
    }

    # Circuit Generation
    CIRCUIT_GENERATION = {
        "max_qubits": 30,  # Further reduced for faster processing
        "min_qubits": 1,
        "max_depth": 200,  # Reduced depth limit
        "min_depth": 1,
        "min_reps": 1,
        "max_reps": 5,
        "min_eval_qubits": 2,
        "max_eval_qubits": 6,
        "measure": False,
        "seed": 4,
        "stopping_probability": 0.3,  # Higher probability to stop (shorter circuits)
        "max_generators": 5,  # Fewer generators for simpler circuits
        "max_circuit_size": 1500,  # Maximum total gates
    }

    # Synergy Rules
    SYNERGY_RULES = [
        # QFT and QPE synergies
        {"trigger": ["QFTGenerator"], "targets": ["QPE"], "multiplier": 2.5},
        {"trigger": ["QPE"], "targets": ["QFTGenerator"], "multiplier": 2.0},
        
        # GHZ synergies
        {"trigger": ["GHZ"], "targets": ["QuantumWalk", "QAOA", "VQEGenerator"], "multiplier": 1.4},
        
        # Variational generator synergies
        {"trigger": ["VQEGenerator", "QAOA", "QNN"], "targets": ["RealAmplitudes", "TwoLocal"], "multiplier": 1.6},
        
        # Entangling generator synergies
        {"trigger": ["GHZ", "WState", "GraphState", "EfficientU2", "QuantumWalk"],
         "targets": ["DeutschJozsa", "GroverNoAncilla"], "multiplier": 1.3},
         
        # Graph state and quantum walk specific synergy
        {"trigger": ["GraphState"], "targets": ["QuantumWalk"], "multiplier": 1.7},
    ]

    # Simulation Configuration
    SIMULATION = {
        "shots": None,  # Exact simulation
        "seed": 0,
        "timeout_seconds": 5,
        "max_qubits_statevector": 20,  # Conservative limit for statevector
        "max_qubits_unitary": 20,  # Conservative limit for unitary/density matrix
        "max_qubits_mps": 20,
        "max_circuit_size": 1000,  # Skip circuits with too many gates
        "infiniquantum": {
             "omit_methods": ["psql","eqc","ducksql"], # Methods to skip. E.g. ["psql", "sqlite"]
             # Available methods: "psql", "sqlite", "ducksql", "eqc", "umbra", "np_mps", "np_one_shot"
             "run_benchmark": True,
             "n_runs": 5
        }
    }

    # Out-of-Core / Limited-Memory Experiments (SIGMOD revision E1)
    # Memory caps enforced via cgroups v2 (systemd-run) for embedded engines
    # and Docker --memory for PostgreSQL. See scripts/ooc/README.md.
    OOC = {
        "caps_gb": [16, 8, 4],            # Memory caps to sweep; baseline comes from prior unconstrained runs
        "engines": ["postgres", "duckdb", "sqlite", "aer"],
        "n_runs": 3,                        # Timed runs per (circuit, cap, engine)
        "warmup_runs": 1,                  # Discarded warm-up runs before timed runs
        "timeout_seconds": 1800,            # 30 min per run
        "drop_page_cache": True,            # sync + echo 3 > /proc/sys/vm/drop_caches between runs
        "tmp_root": "/tmp/inferq_ooc",    # Dir for DuckDB/SQLite temp files (must be on NVMe)
        "results_dir": "scripts/ooc/results",
        "circuits_manifest": "data/ooc/circuits.jsonl",
        # Per-bin circuit counts for stratified sampling (see select_circuits.py).
        # Bins are by QUBIT COUNT, not by prior tracemalloc memory — tracemalloc
        # only sees Python heap, so the published metadata underestimates true
        # footprint by 10-100x. Qubit count directly predicts Aer statevector
        # memory (2^N * 16 B) and is the cleanest OOM-threshold proxy available.
        #   B0 ≤24q  : baseline, Aer fits trivially at every cap
        #   B1 25-27q: ≤2 GB Aer; all caps survive Aer
        #   B2 28-29q: 4-8 GB Aer; fails at cap=4, survives at 8/16
        #   B3 30q   : 16 GB Aer; fails at caps 4 and 8, survives at 16
        #   B4 ≥31q  : 32+ GB Aer; fails at every cap we test (headline)
        "bin_edges_qubits": [25, 28, 30, 31],    # cut points between B0..B4
        "circuits_per_bin": 20,
        "pilot_circuits_per_bin": 5,
        # Postgres Docker
        "postgres_image": "postgres:16",
        "postgres_host_port": 54320,
        # Aer method sweep — ordered by increasing cost; worker runs each and records per-method status
        "aer_methods": ["automatic", "statevector", "MPS", "density_matrix", "stabilizer"],
        # Pad Aer's internal max_memory_mb below the cgroup cap to let Aer raise before OOM-kill
        "aer_max_memory_pad_mb": 512,
    }

    # Storage Configuration
    STORAGE = {
        "local_circuits_dir": "circuits",
        "absolute_storage_path": "/Users/user/Projects/InferQ",  # If set, use this as base path instead of project root
        "cache_file": "circuit_hashes_cache.json",
        "max_local_storage_gb": 50,
    }

    # Azure Configuration
    AZURE = {
        "container_name": "circuits",
        "table_name": "circuits",
        "enabled": False,  # Disable Azure by default for local-only operation
    }

    # Logging Configuration
    LOGGING = {
        "level": "INFO",  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
        "format": "%(asctime)s - %(levelname)s - %(message)s",
        "file_max_size_mb": 100,
        "backup_count": 5,
        "console_output": True,
    }

    def get_env_or_default(self, key, default=None, type_cast=None):
        """Get environment variable or return default."""
        value = os.getenv(key, default)
        if value is not None and type_cast:
            try:
                return type_cast(value)
            except (ValueError, TypeError):
                return default
        return value

    def get_pipeline_config(self):
        """Get pipeline configuration with environment variable overrides."""
        return {
            "workers": self.get_env_or_default("WORKERS", self.optimal_workers, int),
            "batch_size": self.get_env_or_default(
                "BATCH_SIZE", self.PIPELINE_DEFAULTS["batch_size"], int
            ),
            "azure_upload_interval": self.get_env_or_default(
                "AZURE_INTERVAL", self.PIPELINE_DEFAULTS["azure_upload_interval"], int
            ),
            "max_iterations": self.get_env_or_default(
                "ITERATIONS", self.PIPELINE_DEFAULTS["max_iterations"], int
            ),
            "batch_timeout_seconds": self.get_env_or_default(
                "BATCH_TIMEOUT", self.PIPELINE_DEFAULTS["batch_timeout_seconds"], int
            ),
        }

    def get_circuit_config(self):
        """Get circuit generation configuration."""
        return {
            "max_qubits": self.get_env_or_default(
                "MAX_QUBITS", self.CIRCUIT_GENERATION["max_qubits"], int
            ),
            "min_qubits": self.get_env_or_default(
                "MIN_QUBITS", self.CIRCUIT_GENERATION["min_qubits"], int
            ),
            "max_depth": self.get_env_or_default(
                "MAX_DEPTH", self.CIRCUIT_GENERATION["max_depth"], int
            ),
            "min_depth": self.get_env_or_default(
                "MIN_DEPTH", self.CIRCUIT_GENERATION["min_depth"], int
            ),
            "min_reps": self.get_env_or_default(
                "MIN_REPS", self.CIRCUIT_GENERATION["min_reps"], int
            ),
            "max_reps": self.get_env_or_default(
                "MAX_REPS", self.CIRCUIT_GENERATION["max_reps"], int
            ),
            "min_eval_qubits": self.get_env_or_default(
                "MIN_EVAL_QUBITS", self.CIRCUIT_GENERATION["min_eval_qubits"], int
            ),
            "max_eval_qubits": self.get_env_or_default(
                "MAX_EVAL_QUBITS", self.CIRCUIT_GENERATION["max_eval_qubits"], int
            ),
            "measure": self.get_env_or_default(
                "MEASURE", self.CIRCUIT_GENERATION["measure"], bool
            ),
            "seed": self.get_env_or_default(
                "SEED", self.CIRCUIT_GENERATION["seed"], int
            ),
            "stopping_probability": self.get_env_or_default(
                "STOPPING_PROB", self.CIRCUIT_GENERATION["stopping_probability"], float
            ),
            "max_generators": self.get_env_or_default(
                "MAX_GENERATORS", self.CIRCUIT_GENERATION["max_generators"], int
            ),
            "max_circuit_size": self.get_env_or_default(
                "MAX_CIRCUIT_SIZE", self.CIRCUIT_GENERATION["max_circuit_size"], int
            ),
        }

    def get_synergy_rules(self):
        """Get synergy rules configuration."""
        return self.SYNERGY_RULES

    def get_simulation_config(self):
        """Get simulation configuration."""
        return {
            "shots": self.get_env_or_default("SHOTS", self.SIMULATION["shots"], int),
            "seed": self.get_env_or_default("SIM_SEED", self.SIMULATION["seed"], int),
            "timeout_seconds": self.get_env_or_default(
                "SIM_TIMEOUT", self.SIMULATION["timeout_seconds"], int
            ),
            "max_qubits_statevector": self.get_env_or_default(
                "MAX_QUBITS_STATEVECTOR",
                self.SIMULATION["max_qubits_statevector"],
                int,
            ),
            "max_qubits_unitary": self.get_env_or_default(
                "MAX_QUBITS_UNITARY", self.SIMULATION["max_qubits_unitary"], int
            ),
            "max_qubits_mps": self.get_env_or_default(
                "MAX_QUBITS_MPS", self.SIMULATION["max_qubits_mps"], int
            ),
            "max_circuit_size": self.get_env_or_default(
                "SIM_MAX_CIRCUIT_SIZE", self.SIMULATION["max_circuit_size"], int
            ),
            "infiniquantum": {
                "omit_methods": self.get_env_or_default(
                    "IQ_OMIT_METHODS", 
                    self.SIMULATION["infiniquantum"]["omit_methods"], 
                    lambda x: x.split(",") if isinstance(x, str) else x # Allow comma-separated string from env
                ),
                "run_benchmark": self.get_env_or_default(
                    "IQ_RUN_BENCHMARK",
                    self.SIMULATION["infiniquantum"]["run_benchmark"],
                    bool
                ),
                "n_runs": self.get_env_or_default(
                    "IQ_N_RUNS",
                    self.SIMULATION["infiniquantum"]["n_runs"],
                    int
                )
            }
        }

    def get_storage_config(self):
        """Get storage configuration."""
        absolute_path = self.get_env_or_default(
            "ABSOLUTE_STORAGE_PATH", self.STORAGE["absolute_storage_path"]
        )
        local_circuits_dir = self.get_env_or_default(
            "LOCAL_CIRCUITS_DIR", self.STORAGE["local_circuits_dir"]
        )

        # If absolute path is specified, use it as base for circuits directory
        if absolute_path:
            circuits_path = Path(absolute_path) / local_circuits_dir
        else:
            circuits_path = Path(local_circuits_dir)

        return {
            "local_circuits_dir": str(circuits_path),
            "absolute_storage_path": absolute_path,
            "cache_file": self.get_env_or_default(
                "CACHE_FILE", self.STORAGE["cache_file"]
            ),
            "max_local_storage_gb": self.get_env_or_default(
                "MAX_STORAGE_GB", self.STORAGE["max_local_storage_gb"], int
            ),
        }

    def get_ooc_config(self):
        """Get out-of-core experiment configuration with env overrides."""
        cfg = dict(self.OOC)
        caps_env = os.getenv("OOC_CAPS_GB")
        if caps_env:
            cfg["caps_gb"] = [int(x) for x in caps_env.split(",") if x.strip()]
        engines_env = os.getenv("OOC_ENGINES")
        if engines_env:
            cfg["engines"] = [x.strip() for x in engines_env.split(",") if x.strip()]
        cfg["n_runs"] = self.get_env_or_default("OOC_N_RUNS", cfg["n_runs"], int)
        cfg["warmup_runs"] = self.get_env_or_default("OOC_WARMUP", cfg["warmup_runs"], int)
        cfg["timeout_seconds"] = self.get_env_or_default("OOC_TIMEOUT", cfg["timeout_seconds"], int)
        cfg["drop_page_cache"] = self.get_env_or_default("OOC_DROP_CACHE", cfg["drop_page_cache"], bool)
        cfg["tmp_root"] = self.get_env_or_default("OOC_TMP_ROOT", cfg["tmp_root"])
        cfg["results_dir"] = self.get_env_or_default("OOC_RESULTS_DIR", cfg["results_dir"])
        cfg["circuits_manifest"] = self.get_env_or_default("OOC_MANIFEST", cfg["circuits_manifest"])
        cfg["circuits_per_bin"] = self.get_env_or_default("OOC_PER_BIN", cfg["circuits_per_bin"], int)
        cfg["postgres_image"] = self.get_env_or_default("OOC_PG_IMAGE", cfg["postgres_image"])
        cfg["postgres_host_port"] = self.get_env_or_default("OOC_PG_PORT", cfg["postgres_host_port"], int)
        return cfg

    def get_azure_config(self):
        """Get Azure configuration."""
        return {
            "enabled": self.get_env_or_default(
                "AZURE_ENABLED", self.AZURE["enabled"], bool
            ),
            "connection_string": self.get_env_or_default(
                "AZURE_STORAGE_CONNECTION_STRING"
            ),
            "account_name": self.get_env_or_default("AZURE_STORAGE_ACCOUNT_NAME"),
            "account_key": self.get_env_or_default("AZURE_STORAGE_ACCOUNT_KEY"),
            "container_name": self.get_env_or_default(
                "AZURE_CONTAINER", self.AZURE["container_name"]
            ),
            "table_name": self.get_env_or_default(
                "AZURE_TABLE", self.AZURE["table_name"]
            ),
        }

    def print_config_summary(self):
        """Print a summary of current configuration."""
        pipeline_config = self.get_pipeline_config()
        circuit_config = self.get_circuit_config()
        simulation_config = self.get_simulation_config()
        storage_config = self.get_storage_config()
        azure_config = self.get_azure_config()

        print("Pipeline Configuration Summary")
        print("=" * 50)
        print(f"Workers: {pipeline_config['workers']}")
        print(f"Batch size: {pipeline_config['batch_size']}")
        print(f"Azure interval: {pipeline_config['azure_upload_interval']}")
        print(f"Max iterations: {pipeline_config['max_iterations'] or 'Infinite'}")
        print(f"Batch timeout: {pipeline_config['batch_timeout_seconds']}s")
        print()
        print(
            f"Circuit qubits: {circuit_config['min_qubits']}-{circuit_config['max_qubits']}"
        )
        print(
            f"Circuit depth: {circuit_config['min_depth']}-{circuit_config['max_depth']}"
        )
        print(f"Stopping probability: {circuit_config['stopping_probability']}")
        print(f"Max generators: {circuit_config['max_generators']}")
        print(f"Circuit seed: {circuit_config['seed']}")
        print()
        print(f"Simulation shots: {simulation_config['shots'] or 'Exact'}")
        print(f"Simulation seed: {simulation_config['seed']}")
        print(f"Simulation timeout: {simulation_config['timeout_seconds']}s")
        print()
        print(f"Local circuits dir: {storage_config['local_circuits_dir']}")
        print(
            f"Absolute storage path: {storage_config['absolute_storage_path'] or 'Not set (using relative path)'}"
        )
        print(f"Cache file: {storage_config['cache_file']}")
        print(f"Max storage: {storage_config['max_local_storage_gb']}GB")
        print()
        print(f"Azure enabled: {azure_config['enabled']}")
        print(f"Azure container: {azure_config['container_name']}")
        print(f"Azure table: {azure_config['table_name']}")
        print("=" * 50)


# Global configuration instance
config = PipelineConfig()


# Convenience functions for common use cases
def get_pipeline_config():
    """Get pipeline configuration."""
    return config.get_pipeline_config()


def get_circuit_config():
    """Get circuit generation configuration."""
    return config.get_circuit_config()


def get_synergy_rules():
    """Get synergy rules configuration."""
    return config.get_synergy_rules()


def get_simulation_config():
    """Get simulation configuration."""
    return config.get_simulation_config()


def get_storage_config():
    """Get storage configuration."""
    return config.get_storage_config()


def get_azure_config():
    """Get Azure configuration."""
    return config.get_azure_config()


def get_ooc_config():
    """Get out-of-core experiment configuration."""
    return config.get_ooc_config()


if __name__ == "__main__":
    # Print configuration when run directly
    config.print_config_summary()
