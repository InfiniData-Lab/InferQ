#!/bin/bash
# System Information and Environment Setup
# Cross-platform system detection and configuration

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

print_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

# Set performance environment variables
setup_environment() {
    export OMP_NUM_THREADS=4
    export OPENBLAS_NUM_THREADS=4
    export MKL_NUM_THREADS=4
    export NUMEXPR_NUM_THREADS=4
    export PYTHONUNBUFFERED=1
    
    print_status "Performance environment variables set"
}

# Show system information
show_system_info() {
    print_status "System Information:"
    
    # CPU cores - cross-platform
    if command -v nproc >/dev/null 2>&1; then
        CPU_CORES=$(nproc)
    elif command -v sysctl >/dev/null 2>&1; then
        CPU_CORES=$(sysctl -n hw.ncpu)
    else
        CPU_CORES="Unknown"
    fi
    echo "  CPU cores: $CPU_CORES"
    
    # Memory info - cross-platform
    if command -v free >/dev/null 2>&1; then
        MEMORY=$(free -h | grep '^Mem:' | awk '{print $2}')
        echo "  Memory: $MEMORY"
    elif command -v system_profiler >/dev/null 2>&1; then
        MEMORY=$(system_profiler SPHardwareDataType | grep "Memory:" | awk '{print $2, $3}')
        echo "  Memory: $MEMORY"
    else
        echo "  Memory: Unknown"
    fi
    
    # Disk space
    DISK_SPACE=$(df -h . | tail -1 | awk '{print $4}')
    echo "  Disk space: $DISK_SPACE available"
    
    echo ""
    
    # Export CPU_CORES for other scripts to use
    export CPU_CORES
}

# Auto-detect optimal worker count
get_optimal_workers() {
    local workers=${1:-}
    
    if [ -z "$workers" ]; then
        if [ "$CPU_CORES" != "Unknown" ] && [ -n "$CPU_CORES" ]; then
            workers=$((CPU_CORES - 2))
            if [ $workers -lt 1 ]; then
                workers=1
            fi
        else
            workers=4  # Safe default
        fi
    fi
    
    echo $workers
}

# Set process priority for better performance
optimize_process() {
    renice -n -5 $$ 2>/dev/null || print_status "Note: Could not set process priority (requires sudo)"
}

# Show performance monitoring tip
show_monitoring_tip() {
    if command -v htop >/dev/null 2>&1; then
        print_status "💡 Tip: Run 'htop' in another terminal to monitor system resources"
    elif command -v top >/dev/null 2>&1; then
        print_status "💡 Tip: Run 'top' in another terminal to monitor system resources"
    fi
}