#!/bin/bash
# High-Performance Pipeline Runner
# Full production parallel pipeline for continuous operation

set -e  # Exit on any error

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Source utility scripts
source "$SCRIPT_DIR/system_info.sh"
source "$SCRIPT_DIR/azure_check.sh"
source "$SCRIPT_DIR/pipeline_monitor.sh"

# Configuration. The pipeline is invoked through the console script; the process
# pattern is what the monitor greps for when it cleans up.
INFERQ="${INFERQ:-inferq}"
PROCESS_PATTERN="inferq.cli.run"
# Logs follow the same roots the library uses, so a run started here writes where
# `inferq paths` says it will.
LOG_DIR="$("$INFERQ" paths --print state 2>/dev/null || echo ".")/logs"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="${LOG_DIR}/parallel_pipeline_${TIMESTAMP}.log"
PID_FILE="${LOG_DIR}/pipeline.pid"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --workers)
            WORKERS="$2"
            shift 2
            ;;
        --batch-size)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --azure-interval)
            AZURE_INTERVAL="$2"
            shift 2
            ;;
        --iterations)
            ITERATIONS="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --workers N          Number of parallel workers"
            echo "  --batch-size N       Circuits per batch"
            echo "  --azure-interval N   Azure upload interval"
            echo "  --iterations N       Maximum iterations"
            echo "  --help, -h           Show this help message"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Pipeline parameters (can be overridden via environment variables)
# Empty defaults mean centralized config values will be used
WORKERS=${WORKERS:-}  # Auto-detect if not set
ITERATIONS=${ITERATIONS:-}  # Infinite by default  
BATCH_SIZE=${BATCH_SIZE:-}  # Use config default if not set
AZURE_INTERVAL=${AZURE_INTERVAL:-}  # Use config default if not set

# Create necessary directories
mkdir -p "$LOG_DIR"

# Function to handle cleanup on exit
cleanup() {
    cleanup_pipeline "$PID_FILE" "$PROCESS_PATTERN"
}

# Set up signal handlers
trap cleanup EXIT INT TERM

# Check that the console script is on PATH
if ! command -v "$INFERQ" >/dev/null 2>&1; then
    print_error "Error: '$INFERQ' not found on PATH. Run 'uv sync' first, or set INFERQ."
    exit 1
fi

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    print_warning "Warning: No virtual environment detected. Make sure required packages are installed."
fi

print_success "🚀 Starting High-Performance Pipeline (Full Production Mode)"
print_status "=============================================="

# Show system information and setup environment
setup_environment
show_system_info

# Auto-detect workers if not set
WORKERS=$(get_optimal_workers "$WORKERS")

# Check Azure connection
check_azure_connection


# Get config values for display when not overridden
if [ -z "$WORKERS" ] || [ -z "$BATCH_SIZE" ] || [ -z "$AZURE_INTERVAL" ]; then
    CONFIG_VALUES=$(python3 -c "
from inferq.config import get_pipeline_config
config = get_pipeline_config()
print(f\"{config['workers']}|{config['batch_size']}|{config['azure_upload_interval']}\")
" 2>/dev/null || echo "10|100|1000")
    IFS='|' read -r CONFIG_WORKERS CONFIG_BATCH_SIZE CONFIG_AZURE_INTERVAL <<< "$CONFIG_VALUES"
else
    CONFIG_WORKERS=$WORKERS
    CONFIG_BATCH_SIZE=$BATCH_SIZE
    CONFIG_AZURE_INTERVAL=$AZURE_INTERVAL
fi

print_status "Configuration:"
echo "  Workers: ${WORKERS:-$CONFIG_WORKERS}"
echo "  Batch size: ${BATCH_SIZE:-$CONFIG_BATCH_SIZE}"
echo "  Azure upload interval: ${AZURE_INTERVAL:-$CONFIG_AZURE_INTERVAL}"
echo "  Log file: $LOG_FILE"
echo "  PID file: $PID_FILE"
echo ""

# Show performance monitoring tip
show_monitoring_tip

print_success "🏃 Starting pipeline execution..."
print_status "Press Ctrl+C to stop gracefully"
echo ""

# Change to project directory
cd "$PROJECT_DIR"

# Start the pipeline with optimal settings and logging
"$INFERQ" run parallel \
    ${WORKERS:+--workers "$WORKERS"} \
    ${ITERATIONS:+--iterations "$ITERATIONS"} \
    ${BATCH_SIZE:+--batch-size "$BATCH_SIZE"} \
    ${AZURE_INTERVAL:+--azure-interval "$AZURE_INTERVAL"} \
    2>&1 | tee "$LOG_FILE" 

PIPELINE_PID=$!

# Save PID for monitoring
echo $PIPELINE_PID > "$PID_FILE"

EXIT_CODE=$?

# Show results
show_results $EXIT_CODE "$LOG_FILE"

exit $EXIT_CODE
