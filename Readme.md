# InferQ Dataset Generation Pipeline

InferQ is a high-performance framework designed for the large-scale generation, simulation, and analysis of quantum circuits. It features a parallelized pipeline capable of creating diverse quantum circuits (random, structured, algorithmic), simulating them using efficient backends, extracting features, and synchronizing data with Azure Blob & Table Storage.

## 🚀 Key Features

*   **Multi-Generator Architecture**: Supports various circuit generation strategies including GHZ, W-State, Quantum Algorithms (QFT, QAOA, Grover), and random circuits.
*   **High-Performance Pipeline**: utilized `multiprocessing` for parallel circuit generation and simulation.
*   **Circuit Simulation**: Integrated with Qiskit for various simulation methods (Statevector, MPS, etc.).
*   **Feature Extraction**: Automated extraction of static (graph-based) and dynamic (runtime) features from circuits.
*   **Cloud Integration**: Built-in support for Azure Blob Storage (for circuit files) and Azure Table Storage (for metadata/features).
*   **Duplicate Detection**: Intelligent hashing system to avoid processing duplicate circuits.

## 🛠️ Installation

### Prerequisites
*   Python 3.12 or higher
*   Git

### Setup
1.  **Clone the repository**:
    ```bash
    git clone <repository-url>
    cd InferQ
    ```

2.  **Install dependencies**:
    ```bash
    pip install .
    # OR
    pip install -r requirements.txt
    ```

3.  **Environment Setup**:
    Create a `.env` file in the project root with your configuration (primarily for Azure).
    ```bash
    # Example .env content
    AZURE_STORAGE_CONNECTION_STRING="your_connection_string"
    ```
    You can load these variables using the provided script:
    ```bash
    source load_azure_env.sh
    ```

## 🏃 Usage

### Running the Pipeline (Recommended)
The easiest way to run the pipeline is using the provided shell script wrapper, which handles logging and configuration.

```bash
./scripts/run_parallel.sh [OPTIONS]
```

**Options:**
*   `--workers N`: Number of parallel worker processes (default: auto-detected)
*   `--batch-size N`: Number of circuits per batch
*   `--azure-interval N`: Upload to Azure after every N batches
*   `--iterations N`: Maximum number of iterations (default: infinite)

**Example:**
```bash
# Run with 5 workers, batch size of 20
./scripts/run_parallel.sh --workers 5 --batch-size 20
```

### Running Manually (Python)
You can also run the Python entry point directly:

```bash
python main_parallel.py
```

### Project Structure

```text
InferQ/
├── generators/           # Quantum circuit generation logic (QFT, GHZ, Random, etc.)
├── simulators/           # Qiskit-based simulation wrappers
├── feature_extractors/   # Static and dynamic feature extraction
├── pipeline/             # Core pipeline orchestration (Manager, Worker, System Utils)
├── utils/                # Helper utilities (Azure, Hashing, Checkpoints)
├── scripts/              # Shell scripts for running and maintenance
├── config.py             # Centralized configuration
├── main.py               # Single process entry point
├── main_parallel.py      # Multi-process entry point (Production)
└── pyproject.toml        # Project dependencies and metadata
```

## ⚙️ Configuration

The pipeline behavior is controlled by `config.py`. key configurations include:
*   **System**: CPU cores, worker counts.
*   **Generation**: Min/Max qubits, depth, gate sets.
*   **Simulation**: Timeout, methods.
*   **Storage**: paths for local checkpoints and output.

## ☁️ Azure Integration

The pipeline is designed to sync with Azure.
*   **Blob Storage**: Stores the `.qpy` circuit files.
*   **Table Storage**: Stores metadata and extracted features.

Use `scripts/upload_circuits_to_azure.py` or the built-in pipeline integration to manage uploads.

## 🔍 Development

To run environment tests:
```bash
./test-env-scripts/run_all_tests.sh
```
