"""
Quantum Circuit Pipeline Configuration
Centralized configuration for all pipeline components
"""

import multiprocessing as mp
import os
from pathlib import Path

from inferq import paths
from inferq.sql.query_modes import normalize_sql_query_mode


class PipelineConfig:
    """Central configuration for the quantum circuit pipeline."""

    def __init__(self):
        # Every path comes from `inferq.paths`, which is also the only module
        # allowed to create a directory. Constructing the config must stay a pure
        # computation: it runs at import time in several entry points, and an
        # import that mkdirs is what used to drop an empty `logs/` into a fresh
        # clone.
        self.project_root = paths.repo_root()
        self.circuits_dir = paths.circuits_dir()
        self.logs_dir = paths.state_dir() / "logs"

    # System Configuration
    @property
    def cpu_cores(self):
        """Available CPU cores."""
        return mp.cpu_count()

    # Upper bound on worker processes. Beyond this the Azure upload path and the
    # per-worker Aer memory footprint, not the CPU, are the bottleneck.
    MAX_WORKERS = 22

    @property
    def optimal_workers(self):
        """Optimal number of worker processes: cores minus 2, capped."""
        return max(1, min(self.MAX_WORKERS, self.cpu_cores - 2))

    # Pipeline Defaults
    PIPELINE_DEFAULTS = {
        "workers": 1,  # Auto-detect
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
             "omit_methods": ["psql","eqc","ducksql","umbra"], # Methods to skip. E.g. ["psql", "sqlite"]
             # Available methods: "psql", "sqlite", "ducksql", "eqc", "umbra", "np_mps", "np_one_shot"
             "query_mode": "monolithic", # "monolithic", "monolithic_materialized", or "split"
             "run_benchmark": True,
             "n_runs": 5
        }
    }

    # Out-of-Core / Limited-Memory Experiments (SIGMOD revision E1)
    # Memory caps enforced via cgroups v2 (systemd-run) for embedded engines
    # and Docker --memory for PostgreSQL. See experiments/ooc/README.md.
    OOC = {
        "caps_gb": [16, 8, 4],            # Memory caps to sweep; baseline comes from prior unconstrained runs
        # Aer is intentionally dropped from the default sweep: the headline
        # cliff-drop story is already established in the legacy CSV, and the
        # remaining sweep focuses on RDBMS spill behaviour. To run Aer again,
        # set OOC_ENGINES=postgres,duckdb,sqlite,aer or pass --engines.
        "engines": ["postgres", "duckdb", "sqlite"],
        "n_runs": 1,                        # Timed runs per (circuit, cap, engine). Bump via OOC_N_RUNS=3 for variance.
        "warmup_runs": 1,                  # Discarded warm-up runs before timed runs
        "timeout_seconds": 1800,            # 30 min per run
        "drop_page_cache": True,            # sync + echo 3 > /proc/sys/vm/drop_caches between runs
        "tmp_root": "/data/inferq_ooc",    # Dir for DuckDB/SQLite temp files. Must be on a real block device (NVMe), NOT tmpfs — tmpfs writes don't show up in cgroup_io_write_bytes and count against the memory cap.
        # Both resolve through `inferq.paths` at read time (see
        # get_ooc_config) so a checkout never writes results into itself and
        # the manifest is found regardless of where the process was started.
        "results_dir": None,
        "circuits_manifest": None,
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
        "postgres_image": "inferq-ooc-postgres:12.22",
        # Engine-local memory knobs used inside the cgroup/container cap.
        # Keep these small for out-of-core debugging so the DBMS has to use
        # its disk-backed operators before the process reaches the cgroup cap.
        "duckdb_memory_mb": 512,
        "duckdb_pad_mb": 1024,
        "duckdb_threads": 1,
        "sqlite_cache_mb": 64,
        # If > 0, overrides sqlite_cache_mb on a per-trial basis to
        # `cap_gb * 1024 * sqlite_cache_frac`. Lets the SQLite page cache
        # scale with the cgroup cap so cap_gb actually affects runtime
        # (rather than being filled only by the OS page cache).
        "sqlite_cache_frac": 0.0,
        # Optional PostgreSQL overrides for the tuned Docker image. Values <= 0
        # keep the cap-derived defaults in experiments/ooc/docker/pg_entrypoint.sh.
        "postgres_shared_buffers_mb": 0,
        "postgres_work_mem_mb": 0,
        "postgres_maint_work_mem_mb": 0,
        "postgres_effective_cache_mb": 0,
        "postgres_temp_file_limit_mb": 0,
        "postgres_max_worker_processes": 1,
        "postgres_max_parallel_workers": 1,
        "postgres_max_parallel_workers_per_gather": 0,
        "postgres_host_port": 54320,
        # Optional Docker CPU quota applied at the container level. Values <= 0
        # leave Docker's default CPU scheduling unchanged. Set
        # OOC_CONTAINER_CPUS=1 or 2 for comparable single-/few-core runs.
        "container_cpus": 0,
        # Worker runtime image (DuckDB / SQLite / Aer). Built from
        # experiments/ooc/docker/worker/. The orchestrator runs `docker run
        # --memory=cap ... worker_image -m experiments.ooc.worker ...` for every
        # embedded-engine triple, mirroring the postgres path.
        "worker_image": "inferq-ooc-worker:latest",
        # Container runtime for embedded engines: "docker" (cap enforced by
        # Docker --memory) or "none" (direct exec, no cap — smoke test only).
        "runner": "docker",
        # Aer method sweep — ordered by increasing cost; worker runs each and records per-method status
        "aer_methods": ["automatic", "statevector", "matrix_product_state", "density_matrix", "stabilizer"],
        # Qiskit Aer max_parallel_threads. 0 means no explicit Aer thread cap.
        "aer_threads": 0,
        # Pad Aer's internal max_memory_mb below the cgroup cap to let Aer raise before OOM-kill
        "aer_max_memory_pad_mb": 512,
    }

    # Storage Configuration
    STORAGE = {
        "local_circuits_dir": "circuits",
        # When empty, circuits are written relative to the project root. Set
        # ABSOLUTE_STORAGE_PATH to relocate storage to another volume.
        "absolute_storage_path": "",
        "cache_file": "circuit_hashes_cache.json",
        "max_local_storage_gb": 50,
    }

    # Cloud Configuration
    #
    # Bucket and table names are provider-neutral: Azure calls them a container
    # and a table, AWS calls them a bucket and a table, and InferQ uses the same
    # two names for both.
    CLOUD = {
        "provider": "azure",
        "bucket": "circuits",
        "table": "circuits",
        "enabled": False,  # Local-only operation by default
    }

    #: Environment variables that, on their own, mean "this deployment stores
    #: circuits on AWS". Region and credential variables deliberately do not
    #: appear here: they are ambient on any AWS host and would flip an
    #: Azure-backed deployment that merely happens to run on EC2.
    AWS_PROVIDER_HINTS = ("AWS_S3_BUCKET", "AWS_DYNAMODB_TABLE")

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
                if type_cast is bool and isinstance(value, str):
                    return value.strip().lower() in {"1", "true", "yes", "on"}
                return type_cast(value)
            except (ValueError, TypeError):
                return default
        return value

    def get_first_env(self, *keys, default=None, type_cast=None):
        """Read the first variable among ``keys`` that is set.

        Cloud settings have a neutral name and one or more provider-specific
        names kept for compatibility; the neutral name is listed first and
        wins.
        """
        for key in keys:
            if os.getenv(key) is not None:
                return self.get_env_or_default(key, default, type_cast)
        return default

    def get_pipeline_config(self):
        """Get pipeline configuration with environment variable overrides."""
        return {
            "workers": self.get_env_or_default("WORKERS", self.optimal_workers, int),
            "batch_size": self.get_env_or_default(
                "BATCH_SIZE", self.PIPELINE_DEFAULTS["batch_size"], int
            ),
            "azure_upload_interval": self.get_first_env(
                "CLOUD_UPLOAD_INTERVAL",
                "AZURE_INTERVAL",
                default=self.PIPELINE_DEFAULTS["azure_upload_interval"],
                type_cast=int,
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
        query_mode = normalize_sql_query_mode(
            self.get_env_or_default(
                "IQ_QUERY_MODE",
                self.SIMULATION["infiniquantum"]["query_mode"],
                str,
            )
        )
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
                "query_mode": query_mode,
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

        # ABSOLUTE_STORAGE_PATH relocates the store to another volume;
        # LOCAL_CIRCUITS_DIR names the directory inside it. With neither set the
        # store lives under $INFERQ_DATA_DIR, never relative to the process's
        # current working directory.
        if absolute_path:
            circuits_path = Path(absolute_path) / local_circuits_dir
        elif local_circuits_dir != self.STORAGE["local_circuits_dir"]:
            circuits_path = Path(local_circuits_dir)
        else:
            circuits_path = paths.circuits_dir()

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

    @staticmethod
    def default_ooc_manifest() -> Path:
        """Manifest the out-of-core sweep reads when ``OOC_MANIFEST`` is unset.

        Manifests are committed alongside the experiment that produced them, so
        the default is only meaningful inside a checkout; from an installed wheel
        the caller must pass one.
        """
        checkout = paths.repo_root()
        if checkout is None:
            return Path("circuits.jsonl")
        return (
            checkout
            / "experiments"
            / "ooc"
            / "manifests"
            / "circuits_sparse_affine_40_50_h18.jsonl"
        )

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
        cfg["results_dir"] = self.get_env_or_default(
            "OOC_RESULTS_DIR", str(paths.out_dir() / "ooc")
        )
        cfg["circuits_manifest"] = self.get_env_or_default(
            "OOC_MANIFEST", str(self.default_ooc_manifest())
        )
        cfg["circuits_per_bin"] = self.get_env_or_default("OOC_PER_BIN", cfg["circuits_per_bin"], int)
        cfg["postgres_image"] = self.get_env_or_default("OOC_PG_IMAGE", cfg["postgres_image"])
        cfg["duckdb_memory_mb"] = self.get_env_or_default("OOC_DUCKDB_MEMORY_MB", cfg["duckdb_memory_mb"], int)
        cfg["duckdb_pad_mb"] = self.get_env_or_default("OOC_DUCKDB_PAD_MB", cfg["duckdb_pad_mb"], int)
        cfg["duckdb_threads"] = self.get_env_or_default("OOC_DUCKDB_THREADS", cfg["duckdb_threads"], int)
        cfg["sqlite_cache_mb"] = self.get_env_or_default("OOC_SQLITE_CACHE_MB", cfg["sqlite_cache_mb"], int)
        cfg["sqlite_cache_frac"] = self.get_env_or_default("OOC_SQLITE_CACHE_FRAC", cfg["sqlite_cache_frac"], float)
        cfg["postgres_shared_buffers_mb"] = self.get_env_or_default("OOC_PG_SHARED_BUFFERS_MB", cfg["postgres_shared_buffers_mb"], int)
        cfg["postgres_work_mem_mb"] = self.get_env_or_default("OOC_PG_WORK_MEM_MB", cfg["postgres_work_mem_mb"], int)
        cfg["postgres_maint_work_mem_mb"] = self.get_env_or_default("OOC_PG_MAINT_WORK_MEM_MB", cfg["postgres_maint_work_mem_mb"], int)
        cfg["postgres_effective_cache_mb"] = self.get_env_or_default("OOC_PG_EFFECTIVE_CACHE_MB", cfg["postgres_effective_cache_mb"], int)
        cfg["postgres_temp_file_limit_mb"] = self.get_env_or_default("OOC_PG_TEMP_FILE_LIMIT_MB", cfg["postgres_temp_file_limit_mb"], int)
        cfg["postgres_max_worker_processes"] = self.get_env_or_default("OOC_PG_MAX_WORKER_PROCESSES", cfg["postgres_max_worker_processes"], int)
        cfg["postgres_max_parallel_workers"] = self.get_env_or_default("OOC_PG_MAX_PARALLEL_WORKERS", cfg["postgres_max_parallel_workers"], int)
        cfg["postgres_max_parallel_workers_per_gather"] = self.get_env_or_default("OOC_PG_MAX_PARALLEL_WORKERS_PER_GATHER", cfg["postgres_max_parallel_workers_per_gather"], int)
        cfg["postgres_host_port"] = self.get_env_or_default("OOC_PG_PORT", cfg["postgres_host_port"], int)
        cfg["container_cpus"] = self.get_env_or_default("OOC_CONTAINER_CPUS", cfg["container_cpus"], float)
        cfg["worker_image"] = self.get_env_or_default("OOC_WORKER_IMAGE", cfg["worker_image"])
        cfg["runner"] = self.get_env_or_default("OOC_RUNNER", cfg["runner"])
        cfg["aer_threads"] = self.get_env_or_default("OOC_AER_THREADS", cfg["aer_threads"], int)
        return cfg

    def resolve_cloud_provider(self):
        """Decide which cloud backend this deployment uses.

        ``INFERQ_CLOUD_PROVIDER`` is authoritative. When it is unset the
        provider is inferred from the environment: if any variable in
        :attr:`AWS_PROVIDER_HINTS` is set the deployment is on AWS, otherwise
        it is on Azure -- which keeps every existing Azure ``.env`` working
        untouched.
        """
        explicit = self.get_env_or_default("INFERQ_CLOUD_PROVIDER")
        if explicit:
            return explicit.strip().lower()
        if any(os.getenv(var) for var in self.AWS_PROVIDER_HINTS):
            return "aws"
        return self.CLOUD["provider"]

    def get_cloud_config(self):
        """Get cloud storage configuration, provider-neutral.

        The top level carries the settings every provider shares; the
        ``azure`` and ``aws`` keys carry the provider-specific views that the
        corresponding backend consumes.
        """
        provider = self.resolve_cloud_provider()
        enabled = self.get_first_env(
            "CLOUD_ENABLED", "AZURE_ENABLED", default=self.CLOUD["enabled"], type_cast=bool
        )
        bucket = self.get_first_env(
            "CLOUD_BUCKET", "AZURE_CONTAINER", "AWS_S3_BUCKET", default=self.CLOUD["bucket"]
        )
        table = self.get_first_env(
            "CLOUD_TABLE", "AZURE_TABLE", "AWS_DYNAMODB_TABLE", default=self.CLOUD["table"]
        )
        return {
            "provider": provider,
            "enabled": enabled,
            "bucket": bucket,
            "table": table,
            "upload_interval": self.get_first_env(
                "CLOUD_UPLOAD_INTERVAL",
                "AZURE_INTERVAL",
                default=self.PIPELINE_DEFAULTS["azure_upload_interval"],
                type_cast=int,
            ),
            "azure": {
                "enabled": enabled,
                "connection_string": self.get_env_or_default("AZURE_STORAGE_CONNECTION_STRING"),
                "account_name": self.get_env_or_default("AZURE_STORAGE_ACCOUNT_NAME"),
                "account_key": self.get_env_or_default("AZURE_STORAGE_ACCOUNT_KEY"),
                "container_name": bucket,
                "table_name": table,
            },
            "aws": {
                "enabled": enabled,
                "region": self.get_first_env("AWS_REGION", "AWS_DEFAULT_REGION"),
                "bucket": bucket,
                "table": table,
                "endpoint_url": self.get_env_or_default("AWS_ENDPOINT_URL"),
                "profile": self.get_env_or_default("AWS_PROFILE"),
            },
        }

    def get_azure_config(self):
        """Get the Azure view of the cloud configuration."""
        return self.get_cloud_config()["azure"]

    def get_aws_config(self):
        """Get the AWS view of the cloud configuration."""
        return self.get_cloud_config()["aws"]

    def print_config_summary(self):
        """Print a summary of current configuration."""
        pipeline_config = self.get_pipeline_config()
        circuit_config = self.get_circuit_config()
        simulation_config = self.get_simulation_config()
        storage_config = self.get_storage_config()
        cloud_config = self.get_cloud_config()

        print("Pipeline Configuration Summary")
        print("=" * 50)
        print(f"Workers: {pipeline_config['workers']}")
        print(f"Batch size: {pipeline_config['batch_size']}")
        print(f"Cloud upload interval: {pipeline_config['azure_upload_interval']}")
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
        print(f"InfiniQuantumSim query mode: {simulation_config['infiniquantum']['query_mode']}")
        print()
        print(f"Local circuits dir: {storage_config['local_circuits_dir']}")
        print(
            f"Absolute storage path: {storage_config['absolute_storage_path'] or 'Not set (using relative path)'}"
        )
        print(f"Cache file: {storage_config['cache_file']}")
        print(f"Max storage: {storage_config['max_local_storage_gb']}GB")
        print()
        print(f"Cloud provider: {cloud_config['provider']}")
        print(f"Cloud enabled: {cloud_config['enabled']}")
        print(f"Cloud bucket: {cloud_config['bucket']}")
        print(f"Cloud table: {cloud_config['table']}")
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


def get_cloud_config():
    """Get provider-neutral cloud storage configuration."""
    return config.get_cloud_config()


def get_azure_config():
    """Get the Azure view of the cloud configuration."""
    return config.get_azure_config()


def get_aws_config():
    """Get the AWS view of the cloud configuration."""
    return config.get_aws_config()


def get_ooc_config():
    """Get out-of-core experiment configuration."""
    return config.get_ooc_config()


if __name__ == "__main__":
    # Print configuration when run directly
    config.print_config_summary()
