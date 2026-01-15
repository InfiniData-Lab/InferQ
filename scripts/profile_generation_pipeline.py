import sys
import os
import time
import json
import logging
import argparse
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from generators.circuit_merger import CircuitMerger
from generators.lib.generator import BaseParams
from config import get_circuit_config, get_simulation_config, config
from feature_extractors.extractors import extract_features
from simulators.simulate import QuantumSimulator

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("profiler")

def print_profile_report(metrics, title="PROFILING RESULTS"):
    """
    Prints a formatted table of profiling results.
    metrics: dict containing 'generation', 'feature_extraction', 'simulation', 'total' times
    """
    gen_time = metrics['generation']
    feat_time = metrics['feature_extraction']
    sim_time = metrics['simulation']
    total_time = metrics['total']

    print("\n" + "=" * 50)
    print(title)
    print("=" * 50)
    print(f"{'Step':<25} | {'Time (s)':<10} | {'% of Total':<10}")
    print("-" * 50)
    print(f"{'Generation':<25} | {gen_time:<10.4f} | {gen_time/total_time*100:<10.1f}%")
    print(f"{'Feature Extraction':<25} | {feat_time:<10.4f} | {feat_time/total_time*100:<10.1f}%")
    print(f"{'Simulation':<25} | {sim_time:<10.4f} | {sim_time/total_time*100:<10.1f}%")
    print("-" * 50)
    print(f"{'TOTAL':<25} | {total_time:<10.4f} | 100.0%")
    print("=" * 50)

def run_single_iteration(circuitMerger, quantumSimulator, circuit_config):
    """
    Executes one pass of the pipeline and returns timing metrics.
    """
    # 1. Generation
    start_gen = time.perf_counter()
    circ = circuitMerger.generate_hierarchical_circuit(
        stopping_probability=circuit_config['stopping_probability'],
        max_generators=circuit_config['max_generators']
    )
    end_gen = time.perf_counter()
    gen_time = end_gen - start_gen

    # 2. Feature Extraction
    start_feat = time.perf_counter()
    extracted_features = extract_features(circuit=circ)
    end_feat = time.perf_counter()
    feat_time = end_feat - start_feat

    # 3. Simulation
    start_sim = time.perf_counter()
    res = quantumSimulator.simulate_all_methods(circ)
    end_sim = time.perf_counter()
    sim_time = end_sim - start_sim
    


    successful_sims = sum(1 for r in res.values() if r.get('success', False))

    # Identify if any method failed distinctly (not just skipped)
    failed_methods = [m for m, r in res.items() if not r.get('success', False) and not r.get('skipped', False)]

    skipped_methods = [m for m, r in res.items() if r.get('skipped', False)]
    
    # Consider it a failure if:
    # 1. Any method crashed (actual error, not skipped)
    # 2. OR NO simulations succeeded at all (checking skipped or not doesn't matter if result is 0 successes)
    is_failure = (len(failed_methods) > 0) 
    return {
        "generation": gen_time,
        "feature_extraction": feat_time,
        "simulation": sim_time,
        "total": gen_time + feat_time + sim_time,
        "is_failure": is_failure,
        "details": {
            "qubits": circ.num_qubits,
            "depth": circ.depth(),
            "feature_count": len(extracted_features),
            "successful_sims": successful_sims,
            "total_methods": len(res),
            "failed_methods": failed_methods,
            "skipped_methods": skipped_methods
        }
    }

def profile_n_runs(n_runs=1, discard_failures=False):
    print("Initializing components...")
    
    # Configuration
    circuit_config = get_circuit_config()
    simulation_config = get_simulation_config()
    seed = None # Use random seed for different circuits each run

    # Initialize CircuitMerger
    base_params = BaseParams(
        max_qubits=circuit_config['max_qubits'], 
        min_qubits=circuit_config['min_qubits'], 
        max_depth=circuit_config['max_depth'], 
        min_depth=circuit_config['min_depth'], 
        seed=seed, 
        measure=circuit_config['measure']
    )
    circuitMerger = CircuitMerger(base_params=base_params)

    # Initialize QuantumSimulator
    quantumSimulator = QuantumSimulator(
        seed=simulation_config['seed'], 
        shots=simulation_config['shots'],
        timeout_seconds=simulation_config['timeout_seconds'],
        infiniquantum_config=simulation_config.get('infiniquantum')
    )

    print(f"\nStarting profiling for {n_runs} valid runs...")
    print("-" * 50)

    all_metrics = []
    attempts = 0
    
    while len(all_metrics) < n_runs:
        attempts += 1
        current_idx = len(all_metrics) + 1
        logger.info(f"Run {current_idx}/{n_runs} (Attempt {attempts})...")
        
        try:
            metrics = run_single_iteration(circuitMerger, quantumSimulator, circuit_config)
            
            if discard_failures and (metrics['is_failure'] or metrics['details']['total_methods'] != metrics['details']['successful_sims']):
                logger.warning(f" -> Run failed (Methods: {metrics['details']['failed_methods']}). Discarding and retrying...")
                continue
                
            all_metrics.append(metrics)
            # Brief log for progress
            logger.info(f" -> Completed in {metrics['total']:.4f}s (Gen: {metrics['generation']:.2f}s, Ext: {metrics['feature_extraction']:.2f}s, Sim: {metrics['simulation']:.2f}s)")
            
        except Exception as e:
            logger.error(f" -> Exception during run: {e}")
            if discard_failures:
                logger.warning(" -> Discarding due to exception...")
                continue
            else:
                 # If we don't discard, we probably can't add metrics correctly if it crashed.
                 # But if run_single_iteration crashes, we can't get metrics.
                 # So we MUST retry if it crashes fully, unless we want to stop.
                 # Assuming here we skip crashed runs regardless, or better, re-raise if critical.
                 # For now, let's treat exception as a discard case if discard_failures is True, else re-raise to fail script.
                 raise e

    # Calculate Averages
    avg_metrics = {
        "generation": sum(m["generation"] for m in all_metrics) / n_runs,
        "feature_extraction": sum(m["feature_extraction"] for m in all_metrics) / n_runs,
        "simulation": sum(m["simulation"] for m in all_metrics) / n_runs,
    }
    avg_metrics["total"] = avg_metrics["generation"] + avg_metrics["feature_extraction"] + avg_metrics["simulation"]

    # Print Final Report
    print_profile_report(avg_metrics, title=f"AVERAGE PROFILING RESULTS ({n_runs} runs)")

    # Prompt to save
    try:
        save_response = input("\nDo you want to save the timing of the runs in a json? (y/N): ").strip().lower()
        if save_response == 'y':
            output_data = {
                "configuration": {
                    "runs": n_runs,
                    "seed": seed,
                    "timestamp": time.time()
                },
                "average_metrics": avg_metrics,
                "individual_runs": all_metrics
            }
            
            filename = f"profiling_stats_{int(time.time())}.json"
            output_path = Path(filename) # Saves in current directory (root usually)
            
            with open(output_path, 'w') as f:
                json.dump(output_data, f, indent=2)
            print(f"Results saved to {output_path.absolute()}")
            
    except KeyboardInterrupt:
        print("\nSkipping save.")
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Profile the generation pipeline.')
    parser.add_argument('--runs', '-n', type=int, help='Number of pipeline runs to perform')
    parser.add_argument('--strict', action='store_true', help='Discard runs where simulation fails')
    args = parser.parse_args()
    
    runs = args.runs
    if runs is None:
        try:
            val = input("How many runs do you want to perform? [1]: ")
            runs = int(val) if val.strip() else 1
        except ValueError:
            print("Invalid input, defaulting to 1 run.")
            runs = 1
    
    discard_failures = args.strict
    if not args.strict:
        # If not provided via flag, ask user
        try:
             ans = input("Do you want to discard runs where simulations fail (e.g. qiskit/rdbms)? (y/N): ").strip().lower()
             discard_failures = (ans == 'y')
        except KeyboardInterrupt:
             discard_failures = False
             
    profile_n_runs(runs, discard_failures=discard_failures)
