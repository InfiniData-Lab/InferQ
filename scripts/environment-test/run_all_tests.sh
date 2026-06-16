#!/bin/bash
# Master Test Runner for DelftBlue Environment
# Runs all environment verification tests in sequence

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Test directory
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$TEST_DIR")"

# Function to print colored output
print_header() {
    echo -e "${BLUE}$1${NC}"
}

print_success() {
    echo -e "${GREEN}$1${NC}"
}

print_warning() {
    echo -e "${YELLOW}$1${NC}"
}

print_error() {
    echo -e "${RED}$1${NC}"
}

# Function to run a test and capture result
run_test() {
    local test_name="$1"
    local test_script="$2"
    local test_file="$TEST_DIR/$test_script"
    
    print_header "Running $test_name..."
    echo "Script: $test_script"
    echo "Time: $(date)"
    echo ""
    
    if [ ! -f "$test_file" ]; then
        print_error "Test script not found: $test_file"
        return 1
    fi
    
    # Run the test and capture exit code
    if python3 "$test_file"; then
        print_success "✅ $test_name PASSED"
        return 0
    else
        print_error "❌ $test_name FAILED"
        return 1
    fi
}

# Function to show system info
show_system_info() {
    print_header "🖥️  SYSTEM INFORMATION"
    echo "=============================="
    echo "Hostname: $(hostname)"
    echo "Date: $(date)"
    echo "User: $(whoami)"
    echo "Working Directory: $(pwd)"
    echo "Python: $(python3 --version 2>&1)"
    
    # Check for Slurm environment
    if [ -n "$SLURM_JOB_ID" ]; then
        echo "Slurm Job ID: $SLURM_JOB_ID"
        echo "Slurm CPUs: $SLURM_CPUS_PER_TASK"
        echo "Slurm Memory: $SLURM_MEM_PER_NODE MB"
        echo "Slurm Partition: $SLURM_JOB_PARTITION"
    else
        echo "Slurm: Not in job environment"
    fi
    
    # Check virtual environment
    if [ -n "$VIRTUAL_ENV" ]; then
        echo "Virtual Environment: $VIRTUAL_ENV"
    else
        echo "Virtual Environment: None"
    fi
    
    echo ""
}

# Function to create test report
create_test_report() {
    local results=("$@")
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local report_file="test_report_$timestamp.txt"
    
    print_header "📊 CREATING TEST REPORT"
    echo "Report file: $report_file"
    
    {
        echo "DelftBlue Environment Test Report"
        echo "================================="
        echo "Generated: $(date)"
        echo "Hostname: $(hostname)"
        echo "User: $(whoami)"
        echo "Python: $(python3 --version 2>&1)"
        echo ""
        
        if [ -n "$SLURM_JOB_ID" ]; then
            echo "Slurm Environment:"
            echo "  Job ID: $SLURM_JOB_ID"
            echo "  CPUs: $SLURM_CPUS_PER_TASK"
            echo "  Memory: $SLURM_MEM_PER_NODE MB"
            echo "  Partition: $SLURM_JOB_PARTITION"
            echo ""
        fi
        
        echo "Test Results:"
        echo "============="
        
        local passed=0
        local total=${#results[@]}
        
        for result in "${results[@]}"; do
            echo "$result"
            if [[ "$result" == *"PASSED"* ]]; then
                ((passed++))
            fi
        done
        
        echo ""
        echo "Summary: $passed/$total tests passed"
        
        if [ $passed -eq $total ]; then
            echo "Status: ✅ ALL TESTS PASSED - Environment ready!"
        elif [ $passed -ge $((total * 3 / 4)) ]; then
            echo "Status: ⚠️  MOSTLY READY - Minor issues detected"
        else
            echo "Status: ❌ CRITICAL ISSUES - Environment needs attention"
        fi
        
    } > "$report_file"
    
    print_success "Test report saved: $report_file"
}

# Main test execution
main() {
    echo "🧪 DelftBlue Environment Test Suite"
    echo "===================================="
    echo "Starting comprehensive environment verification..."
    echo ""
    
    # Change to project directory
    cd "$PROJECT_DIR"
    
    # Show system information
    show_system_info
    
    # Define tests to run
    declare -a tests=(
        "Python Environment:01_test_python.py"
        "Package Installation:02_test_packages.py"
        "Azure Connectivity:03_test_azure.py"
        "System Resources:04_test_system.py"
        "Pipeline Integration:05_test_pipeline.py"
    )
    
    # Run all tests
    declare -a results=()
    local overall_success=true
    
    for test_entry in "${tests[@]}"; do
        IFS=':' read -r test_name test_script <<< "$test_entry"
        
        echo ""
        echo "=" * 80
        
        if run_test "$test_name" "$test_script"; then
            results+=("✅ $test_name: PASSED")
        else
            results+=("❌ $test_name: FAILED")
            overall_success=false
        fi
        
        echo ""
        sleep 1  # Brief pause between tests
    done
    
    # Final summary
    echo ""
    echo "=" * 80
    print_header "🏁 FINAL SUMMARY"
    echo "=" * 80
    
    local passed=0
    for result in "${results[@]}"; do
        echo "$result"
        if [[ "$result" == *"PASSED"* ]]; then
            ((passed++))
        fi
    done
    
    echo ""
    echo "Overall: $passed/${#results[@]} tests passed"
    
    # Create detailed report
    create_test_report "${results[@]}"
    
    echo ""
    if [ "$overall_success" = true ]; then
        print_success "🎉 ALL TESTS PASSED!"
        print_success "Environment is ready for DelftBlue HPC execution"
        echo ""
        echo "Next steps:"
        echo "1. Submit job: sbatch submit_delftblue.sh"
        echo "2. Monitor: ./monitor_slurm.sh jobs"
        echo "3. Check logs: ./monitor_slurm.sh logs"
        return 0
    else
        print_error "❌ SOME TESTS FAILED"
        print_warning "Review the test output and fix issues before running on HPC"
        echo ""
        echo "Common fixes:"
        echo "1. Install missing packages: pip install -r requirements_delftblue_py38.txt"
        echo "2. Set Azure credentials: export AZURE_STORAGE_CONNECTION_STRING=..."
        echo "3. Check system resources and permissions"
        return 1
    fi
}

# Handle command line arguments
case "$1" in
    "--help"|"-h")
        echo "Usage: $0 [options]"
        echo ""
        echo "Options:"
        echo "  --help, -h    Show this help message"
        echo "  --quick       Run only critical tests (Python, Packages, System)"
        echo "  --no-report   Skip creating test report file"
        echo ""
        echo "This script runs a comprehensive test suite to verify that the"
        echo "DelftBlue HPC environment is properly configured for quantum"
        echo "circuit processing."
        ;;
    "--quick")
        echo "🚀 Running quick test suite..."
        # Override tests array for quick mode
        tests=(
            "Python Environment:01_test_python.py"
            "Package Installation:02_test_packages.py"
            "System Resources:04_test_system.py"
        )
        main
        ;;
    *)
        main "$@"
        ;;
esac