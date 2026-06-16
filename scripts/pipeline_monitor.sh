#!/bin/bash
# Pipeline Process Monitor
# Monitors pipeline execution and handles process management

# Source system info for colored output
source "$(dirname "$0")/system_info.sh"

# Monitor pipeline process
monitor_pipeline() {
    local pipeline_pid=$1
    local log_file=$2
    local pid_file=$3
    
    print_success "Pipeline started with PID: $pipeline_pid"
    print_status "Monitoring pipeline execution..."
    
    # Monitor the process
    while ps -p $pipeline_pid > /dev/null 2>&1; do
        # Check if log file has recent activity (within last 5 minutes)
        if [ -f "$log_file" ]; then
            LAST_MODIFIED=$(stat -f %m "$log_file" 2>/dev/null || stat -c %Y "$log_file" 2>/dev/null || echo 0)
            CURRENT_TIME=$(date +%s)
            TIME_DIFF=$((CURRENT_TIME - LAST_MODIFIED))
            
            if [ $TIME_DIFF -gt 300 ]; then  # 5 minutes
                print_warning "No log activity for 5 minutes. Pipeline may be stuck."
            fi
        fi
        
        # Show progress every 30 seconds
        sleep 30
        print_status "Pipeline still running... (PID: $pipeline_pid)"
        
        # Show last few lines of log for progress indication
        if [ -f "$log_file" ]; then
            echo "Recent activity:"
            tail -3 "$log_file" | sed 's/^/  /'
            echo ""
        fi
    done
    
    # Wait for the process to complete
    wait $pipeline_pid
    local exit_code=$?
    
    # Clean up PID file
    rm -f "$pid_file"
    
    return $exit_code
}

# Cleanup function for graceful shutdown
cleanup_pipeline() {
    local pid_file=$1
    local script_name=$2
    
    echo ""
    print_warning "🛑 Shutting down pipeline..."
    
    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        if ps -p $PID > /dev/null 2>&1; then
            print_warning "Stopping pipeline process (PID: $PID)..."
            kill $PID 2>/dev/null || true
            sleep 2
            if ps -p $PID > /dev/null 2>&1; then
                print_warning "Force killing pipeline process..."
                kill -9 $PID 2>/dev/null || true
            fi
        fi
        rm -f "$pid_file"
    fi
    
    # Kill any remaining Python processes related to the pipeline
    pkill -f "$script_name" 2>/dev/null || true
    
    print_success "✓ Cleanup completed"
}

# Show final results
show_results() {
    local exit_code=$1
    local log_file=$2
    
    echo ""
    if [ $exit_code -eq 0 ]; then
        print_success "✅ Pipeline execution completed successfully!"
    else
        print_error "❌ Pipeline failed with exit code: $exit_code"
    fi
    
    print_status "Final log summary:"
    if [ -f "$log_file" ]; then
        echo "----------------------------------------"
        tail -10 "$log_file"
        echo "----------------------------------------"
        print_status "Full log available at: $log_file"
    fi
}