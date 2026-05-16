import time
import logging
import numpy as np
import gc
import tracemalloc
from timeit import default_timer as timer
from qiskit import transpile
from utils.sql_query_modes import (
    apply_sql_query_mode,
    normalize_sql_query_mode,
    statement_block,
)

# Configure logging
logger = logging.getLogger(__name__)

class IQSGateWrapper:
    """Wrapper for InfiniQuantumSim gates"""
    def __init__(self, tensor, qubits):
        self.tensor = tensor
        self.qubits = qubits

try:
    from InfiniQuantumSim.TLtensor import QuantumCircuit as IQSQuantumCircuit, Gate as IQSGate, INDICES
    import InfiniQuantumSim.mps as iqs_mps
    import InfiniQuantumSim.sqlEinSum as ses
    from InfiniQuantumSim.sql_commands import sql_einsum_query
    import opt_einsum as oe
    INFINI_QUANTUM_AVAILABLE = True
except ImportError as e:
    # logger.debug(f"InfiniQuantumSim import failed: {e}")
    INFINI_QUANTUM_AVAILABLE = False


_IQS_METHOD_ALIASES = {
    "np_mps": "np-mps",
    "np-one-shot": "np-one-shot",
    "np_one_shot": "np-one-shot",
    "duckdb": "ducksql",
}


def _normalise_omit_methods(methods):
    return [_IQS_METHOD_ALIASES.get(method, method) for method in (methods or [])]


def _execute_statement_sequence(method: str, statements: list[str], timeout: int | None, p_size=None):
    """Execute SQL statements in one DB session and return the final result rows."""
    if method == "sqlite":
        import sqlite3

        con = sqlite3.connect(":memory:", check_same_thread=False)
        cur = con.cursor()
        try:
            if p_size is not None:
                ses.change_page_size_sqlite(con, cur, size=p_size)
            result = None
            for statement in statements:
                result = ses.contraction_eval_sqlite(statement, con, cur, timeout=timeout)
                if result is None:
                    return None
            return result
        finally:
            con.close()

    if method in {"psql", "umbra"}:
        import threading

        con, cur = ses.connect_and_setup_db(method)
        try:
            result = None
            for statement in statements:
                result_data = [None]
                exception = [None]
                is_result_statement = not statement.lstrip().upper().startswith("CREATE")

                def run_statement():
                    try:
                        cur.execute(statement)
                        result_data[0] = cur.fetchall() if is_result_statement else []
                    except Exception as exc:
                        exception[0] = exc

                thread = threading.Thread(target=run_statement, daemon=True)
                thread.start()
                thread.join(timeout=timeout)
                if thread.is_alive():
                    try:
                        con.cancel()
                    except Exception:
                        pass
                    thread.join(timeout=0.5)
                    return None
                if exception[0] is not None:
                    raise exception[0]
                result = result_data[0]
                if result is None:
                    return None
            return result
        finally:
            cur.close()
            con.close()

    if method == "ducksql":
        import duckdb
        import threading

        con = duckdb.connect()
        result = [None]
        exception = [None]

        def run_query():
            try:
                final_result = None
                for statement in statements:
                    final_result = con.sql(statement).fetchall()
                result[0] = final_result
            except Exception as exc:
                exception[0] = exc

        thread = threading.Thread(target=run_query, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        if thread.is_alive():
            try:
                con.interrupt()
            except Exception:
                pass
            thread.join(timeout=0.5)
            try:
                con.close()
            except Exception:
                pass
            return None
        try:
            con.close()
        except Exception:
            pass
        if exception[0] is not None:
            raise exception[0]
        return result[0]

    raise ValueError(f"unsupported SQL benchmark method: {method}")


def _time_db_method(method: str, statements: list[str], n_runs: int, timeout: int | None, p_size=None):
    mems = []
    times = []
    timeout_count = 0
    last_result = None

    tracemalloc.start()
    for _ in range(n_runs):
        tic = timer()
        mem_tic, _ = tracemalloc.get_traced_memory()
        last_result = _execute_statement_sequence(method, statements, timeout, p_size=p_size)
        if last_result is None:
            timeout_count += 1
            if timeout_count >= 3:
                break
            continue
        _, mem_toc = tracemalloc.get_traced_memory()
        toc = timer()
        mems.append(mem_toc - mem_tic)
        times.append(toc - tic)
        tracemalloc.clear_traces()
    tracemalloc.stop()
    gc.collect()

    if not times:
        return {"runs": 0, "time": None, "memory": None, "non-zero": None, "timeout": True}
    return {
        "runs": len(times),
        "time": times,
        "memory": mems,
        "non-zero": len(last_result) if last_result is not None else None,
        "timeout": timeout_count > 0,
    }


def _build_iqs_query_and_path(iqs_qc):
    einstein, index_sizes, parameters = iqs_qc.convert_to_einsum()
    opt_rg = oe.RandomGreedy(max_repeats=256, parallel=False)
    views = oe.helpers.build_views(einstein, index_sizes)
    np_path, sql_path_info = oe.contract_path(einstein, *views, optimize=opt_rg)
    query = sql_einsum_query(
        einstein,
        parameters,
        iqs_qc.tensor_uniques,
        path_info=sql_path_info,
        complex=True,
    )
    return einstein, parameters, np_path, query


def _benchmark_iqs_with_query_mode(iqs_qc, n_runs: int, omit_methods: list[str], timeout: int | None, query_mode: str, p_size=None):
    performance = {
        "psql": {},
        "sqlite": {},
        "ducksql": {},
        "umbra": {},
        "np-one-shot": {},
        "np-mps": {},
        "eqc": {},
    }
    einstein, parameters, path, monolithic_query = _build_iqs_query_and_path(iqs_qc)

    np_perf = ses.np_time_contraction_eval(
        einstein,
        parameters,
        iqs_qc.tensor_uniques,
        path,
        iqs_qc,
        n_runs,
        skip_method=omit_methods,
    )
    performance["np-one-shot"] = np_perf["one-shot"]
    performance["np-mps"] = np_perf["mps"]

    mode_output = apply_sql_query_mode(monolithic_query, query_mode)
    statements = mode_output if isinstance(mode_output, list) else [mode_output]

    if "eqc" not in omit_methods:
        performance["eqc"] = {
            "query_mode": query_mode,
            "num_statements": len(statements),
        }

    for method in ("sqlite", "psql", "ducksql", "umbra"):
        if method in omit_methods:
            performance[method] = {"time": None, "memory": None, "non-zero": None}
            continue
        performance[method] = _time_db_method(
            method,
            statements,
            n_runs,
            timeout,
            p_size=p_size,
        )

    sql_query = statement_block(statements) if isinstance(mode_output, list) else mode_output
    return performance, sql_query


def _execute_infiniquantum_simulation(qc, **kwargs):
    """
    Standalone function to run InfiniQuantumSim simulation.
    Can be run in a separate process.
    """
    if not INFINI_QUANTUM_AVAILABLE:
            return {"success": False, "error": "InfiniQuantumSim not installed", "method": "infiniquantum"}
    
    start_time = time.time()
    try:
        
        # Transpile to ensure we only have 1 and 2 qubit gates
        # InfiniQuantumSim handles gates by matrix, so we just need to decompose
        transpiled_qc = transpile(qc, basis_gates=['u', 'cx', 'id', 'rz', 'sx', 'x'], optimization_level=2)
        
        num_qubits = transpiled_qc.num_qubits
        
        # Check if circuit is too large for InfiniQuantumSim
        # InfiniQuantumSim uses single characters for indices. 
        # The number of available characters is limited (around 500-600 based on utils.py).
        # Each gate adds 1 or 2 indices.
        # Rough estimate: num_qubits + 2 * num_gates < len(INDICES)
        # If we exceed this, we should skip or fail gracefully.
        from InfiniQuantumSim.utils import INDICES
        # Use a safer estimate or check exact usage if possible.
        # For now, let's be conservative.
        estimated_indices = num_qubits + 3 * len(transpiled_qc.data) # Increased multiplier to be safe
        if estimated_indices >= len(INDICES):
                logger.warning(f"Skipping InfiniQuantumSim: Circuit  too large (indices limit): {estimated_indices} > {len(INDICES)}")
                return {
                "success": False,
                "error": f"Circuit too large for InfiniQuantumSim (indices limit): {estimated_indices} > {len(INDICES)}",
                "method": "infiniquantum",
                "skipped": True
            }

        iqs_qc = IQSQuantumCircuit(num_qubits=num_qubits)
        
        # Add gates to IQS circuit
        for instruction in transpiled_qc.data:
            op = instruction.operation
            qubits = [transpiled_qc.find_bit(q).index for q in instruction.qubits]
            
            if op.name == 'barrier':
                continue
            if op.name == 'measure':
                continue
                
            matrix = op.to_matrix()
            
            # Reshape matrix for IQS Gate
            # IQS expects (2, 2, 2, 2) for 2-qubit gates, (2, 2) for 1-qubit
            if len(qubits) == 1:
                tensor = matrix
            elif len(qubits) == 2:
                tensor = matrix.reshape(2, 2, 2, 2)
            else:
                raise ValueError(f"Unsupported operation {op.name} on {len(qubits)} qubits")
            
            # Create unique name for parameterized gates to avoid tensor collision if needed
            # But for now, let's just use op.name + id(op) to be safe? 
            # Or just op.name if it's standard. 
            # IQS uses name as key in tensor_uniques. 
            # If we have two RZ gates with different angles, they must have different names.
            if len(op.params) > 0:
                gate_name = f"{op.name}_{id(op)}"
            else:
                gate_name = op.name
            
            gate = IQSGate(qubits, tensor, name=gate_name, two_qubit_gate=(len(qubits) == 2))
            iqs_qc.add_gate(gate)

        # Run benchmark
        n_runs = kwargs.get("n_runs", 1)
        run_benchmark = kwargs.get("run_benchmark", True)
        query_mode = normalize_sql_query_mode(kwargs.get("query_mode", "monolithic"))
        # Default to skipping database methods unless explicitly requested.
        # This prevents connection errors if DBs are not set up.
        oom = _normalise_omit_methods(kwargs.get("oom", ["psql", "sqlite", "ducksql", "umbra", "eqc"]))
        timeout = kwargs.get("timeout", None)
        
        logger.info(f"Running InfiniQuantumSim benchmark with {n_runs} runs (query_mode={query_mode})...")
        if run_benchmark:
            if query_mode == "monolithic":
                benchmark_results = iqs_qc.benchmark_ciruit_performance(n_runs, oom=oom, timeout_seconds=timeout)
                _, _, _, sql_query = _build_iqs_query_and_path(iqs_qc)
            else:
                benchmark_results, sql_query = _benchmark_iqs_with_query_mode(
                    iqs_qc,
                    n_runs=n_runs,
                    omit_methods=oom,
                    timeout=timeout,
                    query_mode=query_mode,
                    p_size=kwargs.get("p_size"),
                )
        else:
            _, _, _, raw_query = _build_iqs_query_and_path(iqs_qc)
            mode_output = apply_sql_query_mode(raw_query, query_mode)
            sql_query = statement_block(mode_output) if isinstance(mode_output, list) else mode_output
            benchmark_results = {}
        
        # Process results
        processed_results = {}
        for method, data in benchmark_results.items():
            if not data: # Empty dict if skipped or failed
                continue
                
            # Calculate averages
            if "memory" in data and "time" in data:
                # Check if lists are None (can happen if initialization failed)
                if data["memory"] is None or data["time"] is None:
                    continue

                # Filter out None values which can occur if a run failed
                mem_values = [x for x in data["memory"] if x is not None]
                time_values = [x for x in data["time"] if x is not None]
                
                if mem_values:
                    mem_avg = np.mean(mem_values)
                    mem_avg_mb = mem_avg / (1024 * 1024)
                else:
                    mem_avg_mb = 0.0
                    
                if time_values:
                    tim_avg = np.mean(time_values)
                else:
                    tim_avg = 0.0

                processed_results[method] = {
                    "memory_avg_mb": mem_avg_mb,
                    "time_avg_s": tim_avg,
                    "raw": data
                }
            elif method == "eqc":
                    # Handle EQC special structure if present (based on user snippet)
                    # But user snippet logic was complex, let's just return raw for now
                    processed_results[method] = data

        execution_time = time.time() - start_time
        return {
            "success": True,
            "method": "infiniquantum",
            "benchmark_results": processed_results,
            "execution_time": execution_time,
            "backend_name": "InfiniQuantumSim",
            "sql_query": sql_query,
            "sql_query_mode": query_mode,
        }

    except Exception as e:
        logger.error(f"InfiniQuantumSim failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "method": "infiniquantum",
            "execution_time": time.time() - start_time
        }


def extract_sql(qc, circuit_hash: str, sql_only:bool=False, query_mode: str = "monolithic") -> dict:
        """Extract SQL features from a quantum circuit"""
        from feature_extractors.sql_analyzer import SQLFeatureExtractor
        
        try:
            if not INFINI_QUANTUM_AVAILABLE:
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": False,
                    "updates": {},
                    "error": "InfiniQuantumSim not installed"
                }
            
            # Transpile to ensure we only have 1 and 2 qubit gates
            transpiled_qc = transpile(qc, basis_gates=['u', 'cx', 'id', 'rz', 'sx', 'x'], optimization_level=2)
            num_qubits = transpiled_qc.num_qubits
            
            # Check if circuit is too large
            estimated_indices = num_qubits + 3 * len(transpiled_qc.data)
            if estimated_indices >= len(INDICES):
                logger.warning(f"Skipping {circuit_hash}: Circuit too large (indices limit)")
                return {
                    "hash": circuit_hash,
                    "success": False,
                    "skipped": True,
                    "updates": {},
                    "error": "Circuit too large for InfiniQuantumSim"
                }
            
            # Create IQS circuit
            iqs_qc = IQSQuantumCircuit(num_qubits=num_qubits)
            
            # Add gates to IQS circuit
            for instruction in transpiled_qc.data:
                op = instruction.operation
                qubits = [transpiled_qc.find_bit(q).index for q in instruction.qubits]
                
                if op.name in ['barrier', 'measure']:
                    continue
                
                matrix = op.to_matrix()
                
                if len(qubits) == 1:
                    tensor = matrix
                elif len(qubits) == 2:
                    tensor = matrix.reshape(2, 2, 2, 2)
                else:
                    raise ValueError(f"Unsupported operation {op.name} on {len(qubits)} qubits")
                
                gate_name = f"{op.name}_{id(op)}" if len(op.params) > 0 else op.name
                gate = IQSGate(qubits, tensor, name=gate_name, two_qubit_gate=(len(qubits) == 2))
                iqs_qc.add_gate(gate)
            
            # Generate SQL query and extract features
            query_mode = normalize_sql_query_mode(query_mode)
            _, _, _, raw_query = _build_iqs_query_and_path(iqs_qc)
            mode_output = apply_sql_query_mode(raw_query, query_mode)
            sql_query = statement_block(mode_output) if isinstance(mode_output, list) else mode_output
            if sql_only:
                return sql_query
            sql_features, join_edges = SQLFeatureExtractor.extract_sql_features(sql_query)
            
            # Prepare updates
            updates = {}
            for feat_name, count in sql_features.items():
                updates[f"infinidata_quantum_sql_{feat_name}"] = count
            updates["infinidata_quantum_sql_num_joins"] = len(join_edges)
            
            return {
                "hash": circuit_hash,
                "success": True,
                "skipped": False,
                "updates": updates,
                "error": None
            }
            
        except Exception as e:
            logger.error(f"Failed to extract SQL features for {circuit_hash}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return {
                "hash": circuit_hash,
                "success": False,
                "skipped": False,
                "updates": {},
                "error": str(e)
            }


def _wrapper_run_iqs(qc, kwargs, q):
    """Wrapper to run IQS simulation in a process and put result in queue"""
    try:
        res = _execute_infiniquantum_simulation(qc, **kwargs)
        q.put(res)
    except Exception as e:
        q.put({"success": False, "error": str(e), "method": "infiniquantum"})
