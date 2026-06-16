#!/usr/bin/env python3
"""
Test 2: Package Installation Verification
Tests if all required packages are installed and importable
"""

import sys
import importlib
import pkg_resources
from packaging import version

# Critical packages for the quantum circuit pipeline
CRITICAL_PACKAGES = {
    'qiskit': {
        'exact_version': '2.0.1',
        'description': 'Quantum computing framework'
    },
    'qiskit_aer': {
        'exact_version': '0.17.0',
        'description': 'Qiskit Aer quantum simulator'
    },
    'numpy': {
        'exact_version': '2.2.5',
        'description': 'Numerical computing'
    },
    'scipy': {
        'exact_version': '1.15.3',
        'description': 'Scientific computing'
    },
    'pandas': {
        'exact_version': '2.2.3',
        'description': 'Data manipulation'
    },
    'networkx': {
        'exact_version': '3.4.2',
        'description': 'Graph analysis'
    }
}

OPTIONAL_PACKAGES = {
    'azure.storage.blob': {
        'exact_version': '12.25.1',
        'description': 'Azure Blob Storage'
    },
    'azure.data.tables': {
        'min_version': '12.7.0',
        'description': 'Azure Table Storage'
    },
    'azure.identity': {
        'exact_version': '1.23.0',
        'description': 'Azure Identity'
    },
    'azure.core': {
        'exact_version': '1.34.0',
        'description': 'Azure Core'
    },
    'psutil': {
        'exact_version': '7.0.0',
        'description': 'System monitoring'
    },
    'tqdm': {
        'exact_version': '4.67.1',
        'description': 'Progress bars'
    },
    'matplotlib': {
        'min_version': '3.10.3',
        'description': 'Plotting'
    }
}

def get_package_version(package_name):
    """Get installed version of a package"""
    try:
        # Handle packages with dots in name
        if '.' in package_name:
            # For packages like azure.storage.blob, try the parent package
            parent_package = package_name.split('.')[0]
            return pkg_resources.get_distribution(parent_package).version
        else:
            return pkg_resources.get_distribution(package_name).version
    except pkg_resources.DistributionNotFound:
        return None

def test_package_import(package_name):
    """Test if a package can be imported"""
    try:
        importlib.import_module(package_name)
        return True
    except ImportError:
        return False

def check_version_compatibility(installed_version, min_version=None, max_version=None, exact_version=None):
    """Check if installed version is compatible"""
    if not installed_version:
        return False, "Not installed"
    
    try:
        installed = version.parse(installed_version)
        
        # Check for exact version match first
        if exact_version:
            exact_ver = version.parse(exact_version)
            if installed == exact_ver:
                return True, "Exact match"
            else:
                return False, f"Version mismatch (need exactly {exact_version}, got {installed_version})"
        
        # Check min/max version ranges
        if min_version:
            min_ver = version.parse(min_version)
            if installed < min_ver:
                return False, f"Too old (need >={min_version})"
        
        if max_version:
            max_ver = version.parse(max_version)
            if installed >= max_ver:
                return False, f"Too new (need <{max_version})"
        
        return True, "Compatible"
    
    except Exception as e:
        return False, f"Version check failed: {e}"

def test_critical_packages():
    """Test critical packages"""
    print("🔧 Testing Critical Packages...")
    
    results = []
    all_good = True
    
    for package_name, requirements in CRITICAL_PACKAGES.items():
        print(f"\n   Testing {package_name}...")
        
        # Test import
        can_import = test_package_import(package_name)
        print(f"     Import: {'✅' if can_import else '❌'}")
        
        # Test version
        installed_version = get_package_version(package_name)
        if installed_version:
            print(f"     Version: {installed_version}")
            
            compatible, reason = check_version_compatibility(
                installed_version,
                requirements.get('min_version'),
                requirements.get('max_version'),
                requirements.get('exact_version')
            )
            print(f"     Compatibility: {'✅' if compatible else '❌'} {reason}")
        else:
            print(f"     Version: ❌ Not found")
            compatible = False
        
        package_ok = can_import and compatible
        results.append((package_name, package_ok, requirements['description']))
        
        if not package_ok:
            all_good = False
    
    return results, all_good

def test_optional_packages():
    """Test optional packages"""
    print("\n🔧 Testing Optional Packages...")
    
    results = []
    
    for package_name, requirements in OPTIONAL_PACKAGES.items():
        print(f"\n   Testing {package_name}...")
        
        # Test import
        can_import = test_package_import(package_name)
        print(f"     Import: {'✅' if can_import else '⚠️'}")
        
        # Test version
        installed_version = get_package_version(package_name)
        if installed_version:
            print(f"     Version: {installed_version}")
            
            compatible, reason = check_version_compatibility(
                installed_version,
                requirements.get('min_version'),
                requirements.get('max_version'),
                requirements.get('exact_version')
            )
            print(f"     Compatibility: {'✅' if compatible else '⚠️'} {reason}")
        else:
            print(f"     Version: ⚠️ Not found")
            compatible = False
        
        package_ok = can_import and compatible
        results.append((package_name, package_ok, requirements['description']))
    
    return results

def test_quantum_functionality():
    """Test basic quantum computing functionality"""
    print("\n⚛️  Testing Quantum Functionality...")
    
    try:
        from qiskit import QuantumCircuit, transpile
        from qiskit_aer import AerSimulator
        
        # Create a simple quantum circuit
        qc = QuantumCircuit(2, 2)
        qc.h(0)
        qc.cx(0, 1)
        qc.measure_all()
        
        print("     ✅ Quantum circuit creation")
        
        # Test simulator
        simulator = AerSimulator()
        compiled_circuit = transpile(qc, simulator)
        
        print("     ✅ Circuit compilation")
        
        # Test execution (small test)
        job = simulator.run(compiled_circuit, shots=10)
        result = job.result()
        counts = result.get_counts()
        
        print("     ✅ Quantum simulation")
        print(f"     Sample results: {dict(list(counts.items())[:2])}")
        
        return True
        
    except Exception as e:
        print(f"     ❌ Quantum functionality failed: {e}")
        return False

def main():
    """Run all package tests"""
    print("=" * 60)
    print("📦 PACKAGE INSTALLATION TEST")
    print("=" * 60)
    
    # Test critical packages
    critical_results, critical_ok = test_critical_packages()
    
    # Test optional packages
    optional_results = test_optional_packages()
    
    # Test quantum functionality
    quantum_ok = test_quantum_functionality()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 PACKAGE TEST SUMMARY")
    print("=" * 60)
    
    print("\nCritical Packages:")
    critical_passed = 0
    for package_name, result, description in critical_results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status:8} {package_name:15} - {description}")
        if result:
            critical_passed += 1
    
    print(f"\nCritical: {critical_passed}/{len(critical_results)} packages")
    
    print("\nOptional Packages:")
    optional_passed = 0
    for package_name, result, description in optional_results:
        status = "✅ PASS" if result else "⚠️  SKIP"
        print(f"  {status:8} {package_name:15} - {description}")
        if result:
            optional_passed += 1
    
    print(f"Optional: {optional_passed}/{len(optional_results)} packages")
    
    print(f"\nQuantum Functionality: {'✅ PASS' if quantum_ok else '❌ FAIL'}")
    
    # Overall result
    if critical_ok and quantum_ok:
        print("\n🎉 All critical packages are ready!")
        return 0
    else:
        print("\n❌ Critical package issues found")
        return 1

if __name__ == "__main__":
    exit(main())