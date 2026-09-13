#!/usr/bin/env python3
"""
Test 1: Python Environment Verification
Tests Python version, virtual environment, and basic functionality
"""

import importlib.util
import os
import platform
import sys
from pathlib import Path


def test_python_version():
    """Test if Python version is compatible"""
    print("🐍 Testing Python Version...")
    
    version = sys.version_info
    print(f"   Python version: {version.major}.{version.minor}.{version.micro}")
    print(f"   Python executable: {sys.executable}")
    print(f"   Platform: {platform.platform()}")
    
    # Check if version is acceptable (3.8+)
    if version.major == 3 and version.minor >= 8:
        print("   ✅ Python version is compatible")
        return True
    else:
        print("   ❌ Python version too old (need 3.8+)")
        return False

def test_virtual_environment():
    """Test virtual environment setup"""
    print("\n🏠 Testing Virtual Environment...")
    
    venv_path = os.environ.get('VIRTUAL_ENV')
    if venv_path:
        print(f"   Virtual environment: {venv_path}")
        print("   ✅ Virtual environment is active")
        return True
    else:
        print("   ⚠️  No virtual environment detected")
        print("   This may be okay if using system packages")
        return True  # Not critical

def test_python_path():
    """Test Python path and module discovery"""
    print("\n📁 Testing Python Path...")
    
    print("   Python path entries:")
    for i, path in enumerate(sys.path[:5]):  # Show first 5 entries
        print(f"     {i+1}. {path}")
    
    # InferQ is an installed distribution, so what matters is whether the
    # package resolves — not whether the current directory happens to be on
    # sys.path, which was only ever true for the old flat layout.
    if importlib.util.find_spec("inferq") is not None:
        print("   ✅ inferq resolves on the import path")
        return True
    print("   ❌ inferq does not resolve; run `uv sync` or `pip install -e .`")
    return False

def test_basic_imports():
    """Test basic Python standard library imports"""
    print("\n📦 Testing Basic Python Imports...")
    
    basic_modules = [
        'os', 'sys', 'json', 'multiprocessing', 
        'pathlib', 'datetime', 'logging', 'argparse'
    ]
    
    all_good = True
    for module in basic_modules:
        try:
            __import__(module)
            print(f"   ✅ {module}")
        except ImportError as e:
            print(f"   ❌ {module}: {e}")
            all_good = False
    
    return all_good

def test_file_permissions():
    """Test file system permissions"""
    print("\n📝 Testing File Permissions...")
    
    # Test write permissions in current directory
    test_file = Path("test_write_permission.tmp")
    try:
        test_file.write_text("test")
        test_file.unlink()
        print("   ✅ Write permissions in current directory")
        write_ok = True
    except Exception as e:
        print(f"   ❌ Cannot write to current directory: {e}")
        write_ok = False
    
    # Test directory creation
    test_dir = Path("test_dir_permission")
    try:
        test_dir.mkdir(exist_ok=True)
        test_dir.rmdir()
        print("   ✅ Directory creation permissions")
        dir_ok = True
    except Exception as e:
        print(f"   ❌ Cannot create directories: {e}")
        dir_ok = False
    
    return write_ok and dir_ok

def main():
    """Run all Python environment tests"""
    print("=" * 60)
    print("🧪 PYTHON ENVIRONMENT TEST")
    print("=" * 60)
    
    tests = [
        ("Python Version", test_python_version),
        ("Virtual Environment", test_virtual_environment),
        ("Python Path", test_python_path),
        ("Basic Imports", test_basic_imports),
        ("File Permissions", test_file_permissions),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 PYTHON TEST SUMMARY")
    print("=" * 60)
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:8} {test_name}")
        if result:
            passed += 1
    
    print(f"\nPassed: {passed}/{len(results)} tests")
    
    if passed == len(results):
        print("🎉 All Python environment tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed - check configuration")
        return 1

if __name__ == "__main__":
    exit(main())