#!/usr/bin/env python3
"""
Test 4: System Resources and Performance
Tests system capabilities, memory, CPU, and performance settings
"""

import os
import psutil
import multiprocessing as mp
import platform
import time
from pathlib import Path

def test_system_info():
    """Test basic system information"""
    print("💻 Testing System Information...")
    
    # Basic system info
    print(f"   Platform: {platform.platform()}")
    print(f"   Architecture: {platform.architecture()[0]}")
    print(f"   Processor: {platform.processor()}")
    print(f"   Python implementation: {platform.python_implementation()}")
    
    # Check if we're on DelftBlue
    hostname = platform.node()
    if 'delftblue' in hostname.lower() or 'login' in hostname.lower():
        print("   ✅ Running on DelftBlue HPC system")
        on_hpc = True
    else:
        print("   ⚠️  Not on DelftBlue (testing locally)")
        on_hpc = False
    
    # Check for Slurm environment
    slurm_job_id = os.getenv('SLURM_JOB_ID')
    if slurm_job_id:
        print(f"   ✅ Running in Slurm job: {slurm_job_id}")
        print(f"   Slurm CPUs: {os.getenv('SLURM_CPUS_PER_TASK', 'Not set')}")
        print(f"   Slurm Memory: {os.getenv('SLURM_MEM_PER_NODE', 'Not set')} MB")
        in_slurm = True
    else:
        print("   ⚠️  Not in Slurm job (login node or local)")
        in_slurm = False
    
    return on_hpc, in_slurm

def test_cpu_resources():
    """Test CPU resources and capabilities"""
    print("\n🔧 Testing CPU Resources...")
    
    # CPU count
    logical_cpus = psutil.cpu_count(logical=True)
    physical_cpus = psutil.cpu_count(logical=False)
    
    print(f"   Logical CPUs: {logical_cpus}")
    print(f"   Physical CPUs: {physical_cpus}")
    
    # CPU frequency
    try:
        cpu_freq = psutil.cpu_freq()
        if cpu_freq:
            print(f"   CPU Frequency: {cpu_freq.current:.1f} MHz (max: {cpu_freq.max:.1f})")
        else:
            print("   CPU Frequency: Not available")
    except Exception:
        print("   CPU Frequency: Not available")
    
    # CPU usage test
    print("   Testing CPU performance...")
    cpu_percent = psutil.cpu_percent(interval=1)
    print(f"   Current CPU usage: {cpu_percent:.1f}%")
    
    # Multiprocessing test
    try:
        mp_cpu_count = mp.cpu_count()
        print(f"   Multiprocessing CPU count: {mp_cpu_count}")
        
        if mp_cpu_count >= 4:
            print("   ✅ Sufficient CPUs for parallel processing")
            cpu_ok = True
        else:
            print("   ⚠️  Limited CPUs - may affect performance")
            cpu_ok = True  # Still workable
    except Exception as e:
        print(f"   ❌ Multiprocessing test failed: {e}")
        cpu_ok = False
    
    return cpu_ok

def test_memory_resources():
    """Test memory resources"""
    print("\n💾 Testing Memory Resources...")
    
    # Memory info
    memory = psutil.virtual_memory()
    
    total_gb = memory.total / (1024**3)
    available_gb = memory.available / (1024**3)
    used_gb = memory.used / (1024**3)
    
    print(f"   Total Memory: {total_gb:.1f} GB")
    print(f"   Available Memory: {available_gb:.1f} GB")
    print(f"   Used Memory: {used_gb:.1f} GB ({memory.percent:.1f}%)")
    
    # Check if sufficient for quantum computing
    if available_gb >= 8:
        print("   ✅ Sufficient memory for quantum computing")
        memory_ok = True
    elif available_gb >= 4:
        print("   ⚠️  Limited memory - may need smaller circuits")
        memory_ok = True
    else:
        print("   ❌ Insufficient memory for quantum computing")
        memory_ok = False
    
    # Swap info
    try:
        swap = psutil.swap_memory()
        swap_gb = swap.total / (1024**3)
        print(f"   Swap Memory: {swap_gb:.1f} GB ({swap.percent:.1f}% used)")
    except Exception:
        print("   Swap Memory: Not available")
    
    return memory_ok

def test_disk_resources():
    """Test disk space and I/O"""
    print("\n💿 Testing Disk Resources...")
    
    # Disk usage for current directory
    disk = psutil.disk_usage('.')
    
    total_gb = disk.total / (1024**3)
    free_gb = disk.free / (1024**3)
    used_gb = disk.used / (1024**3)
    
    print(f"   Total Disk: {total_gb:.1f} GB")
    print(f"   Free Disk: {free_gb:.1f} GB")
    print(f"   Used Disk: {used_gb:.1f} GB ({(used_gb/total_gb)*100:.1f}%)")
    
    # Check if sufficient for circuit storage
    if free_gb >= 10:
        print("   ✅ Sufficient disk space")
        disk_ok = True
    elif free_gb >= 5:
        print("   ⚠️  Limited disk space - monitor usage")
        disk_ok = True
    else:
        print("   ❌ Insufficient disk space")
        disk_ok = False
    
    # Test write speed (simple test)
    print("   Testing disk write speed...")
    test_file = Path("test_disk_speed.tmp")
    
    try:
        start_time = time.time()
        test_data = b"0" * (1024 * 1024)  # 1MB
        
        with open(test_file, 'wb') as f:
            for _ in range(10):  # Write 10MB
                f.write(test_data)
        
        write_time = time.time() - start_time
        write_speed = 10 / write_time  # MB/s
        
        test_file.unlink()  # Clean up
        
        print(f"   Write Speed: {write_speed:.1f} MB/s")
        
        if write_speed >= 50:
            print("   ✅ Good disk performance")
        elif write_speed >= 10:
            print("   ⚠️  Moderate disk performance")
        else:
            print("   ⚠️  Slow disk performance")
            
    except Exception as e:
        print(f"   ⚠️  Disk speed test failed: {e}")
    
    return disk_ok

def test_environment_variables():
    """Test performance-related environment variables"""
    print("\n🌍 Testing Environment Variables...")
    
    # Threading environment variables
    threading_vars = [
        'OMP_NUM_THREADS',
        'OPENBLAS_NUM_THREADS', 
        'MKL_NUM_THREADS',
        'NUMEXPR_NUM_THREADS'
    ]
    
    for var in threading_vars:
        value = os.getenv(var)
        if value:
            print(f"   ✅ {var}: {value}")
        else:
            print(f"   ⚠️  {var}: Not set")
    
    # Python environment variables
    python_vars = [
        'PYTHONUNBUFFERED',
        'PYTHONDONTWRITEBYTECODE',
        'PYTHONHASHSEED'
    ]
    
    for var in python_vars:
        value = os.getenv(var)
        if value:
            print(f"   ✅ {var}: {value}")
        else:
            print(f"   ⚠️  {var}: Not set")
    
    return True  # Environment variables are optional

def test_quantum_performance():
    """Test quantum computing performance"""
    print("\n⚛️  Testing Quantum Performance...")
    
    try:
        from qiskit import QuantumCircuit, transpile
        from qiskit_aer import AerSimulator
        import time
        
        # Create a moderately complex circuit
        qc = QuantumCircuit(4, 4)
        for i in range(4):
            qc.h(i)
        for i in range(3):
            qc.cx(i, i+1)
        qc.measure_all()
        
        simulator = AerSimulator()
        compiled_circuit = transpile(qc, simulator)
        
        # Time the simulation
        start_time = time.time()
        job = simulator.run(compiled_circuit, shots=1000)
        job.result()
        sim_time = time.time() - start_time
        
        print(f"   4-qubit simulation (1000 shots): {sim_time:.3f} seconds")
        
        if sim_time < 1.0:
            print("   ✅ Excellent quantum performance")
            perf_ok = True
        elif sim_time < 5.0:
            print("   ✅ Good quantum performance")
            perf_ok = True
        else:
            print("   ⚠️  Slow quantum performance")
            perf_ok = True  # Still workable
        
        return perf_ok
        
    except Exception as e:
        print(f"   ❌ Quantum performance test failed: {e}")
        return False

def main():
    """Run all system tests"""
    print("=" * 60)
    print("🖥️  SYSTEM RESOURCES TEST")
    print("=" * 60)
    
    # Run tests
    on_hpc, in_slurm = test_system_info()
    cpu_ok = test_cpu_resources()
    memory_ok = test_memory_resources()
    disk_ok = test_disk_resources()
    env_ok = test_environment_variables()
    quantum_perf_ok = test_quantum_performance()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 SYSTEM TEST SUMMARY")
    print("=" * 60)
    
    tests = [
        ("CPU Resources", cpu_ok),
        ("Memory Resources", memory_ok),
        ("Disk Resources", disk_ok),
        ("Environment Variables", env_ok),
        ("Quantum Performance", quantum_perf_ok)
    ]
    
    passed = 0
    for test_name, result in tests:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:8} {test_name}")
        if result:
            passed += 1
    
    print(f"\nPassed: {passed}/{len(tests)} tests")
    
    # System-specific recommendations
    print("\n💡 RECOMMENDATIONS:")
    if on_hpc:
        print("   • Running on HPC - optimize for high throughput")
        if in_slurm:
            print("   • In Slurm job - use all allocated resources")
        else:
            print("   • On login node - use minimal resources for testing")
    else:
        print("   • Running locally - adjust batch sizes for your system")
    
    if passed >= 4:
        print("\n🎉 System is ready for quantum computing!")
        return 0
    else:
        print("\n⚠️  System has some limitations - adjust configuration")
        return 1

if __name__ == "__main__":
    exit(main())