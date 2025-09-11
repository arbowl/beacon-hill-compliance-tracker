#!/usr/bin/env python3
"""
Build script for MA Rules project.
Creates a standalone executable using PyInstaller and packages necessary files.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return result
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(f"   Command: {cmd}")
        print(f"   Error: {e.stderr}")
        sys.exit(1)


def main():
    """Main build process."""
    print("🚀 Starting MA Rules build process...")
    
    # Check if we're in the right directory
    if not os.path.exists("app.py"):
        print("❌ Error: app.py not found. Please run this script from the project root directory.")
        sys.exit(1)
    
    # Check if we're in a virtual environment
    if not hasattr(sys, 'real_prefix') and not (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("⚠️  Warning: Not running in a virtual environment.")
        print("   It's recommended to use a virtual environment for building.")
        print("   Create one with: python -m venv venv")
        print("   Activate with: venv\\Scripts\\activate (Windows) or source venv/bin/activate (Linux/Mac)")
        print("   Then install dependencies: pip install -r requirements.txt")
        response = input("   Continue anyway? (y/N): ").strip().lower()
        if response != 'y':
            print("   Build cancelled.")
            sys.exit(1)
    
    # Check if PyInstaller is available
    try:
        subprocess.run(["pyinstaller", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Error: PyInstaller not found. Please install it with: pip install pyinstaller")
        sys.exit(1)
    
    # Clean up previous builds
    print("🧹 Cleaning up previous builds...")
    for folder in ["build", "dist", "release"]:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"   Removed {folder}/")
    
    # Check if app.spec exists, otherwise use app.py
    if os.path.exists("app.spec"):
        print("📋 Found app.spec file, using it for PyInstaller")
        pyinstaller_cmd = "pyinstaller app.spec -F"
    else:
        print("📋 No app.spec found, using app.py directly")
        pyinstaller_cmd = "pyinstaller app.py -F"
    
    # Run PyInstaller
    run_command(pyinstaller_cmd, "Building executable with PyInstaller")
    
    # Verify dist folder was created
    if not os.path.exists("dist"):
        print("❌ Error: dist folder was not created by PyInstaller")
        sys.exit(1)
    
    # Copy necessary files to dist folder
    print("📦 Copying necessary files to dist folder...")
    
    files_to_copy = [
        "config.yaml",
        "requirements.txt"
    ]
    
    # Copy files that exist
    for file in files_to_copy:
        if os.path.exists(file):
            shutil.copy2(file, "dist/")
            print(f"   Copied {file}")
        else:
            print(f"   ⚠️  Warning: {file} not found, skipping")
    
    # Copy cache.json if it exists (optional)
    if os.path.exists("cache.json"):
        shutil.copy2("cache.json", "dist/")
        print("   Copied cache.json")
    
    # Create out directory in dist for output files
    out_dir = os.path.join("dist", "out")
    os.makedirs(out_dir, exist_ok=True)
    print(f"   Created {out_dir}/ directory for output files")
    
    # Remove build folder
    if os.path.exists("build"):
        shutil.rmtree("build")
        print("🗑️  Removed build/ folder")
    
    # Rename dist to release
    if os.path.exists("release"):
        shutil.rmtree("release")
    os.rename("dist", "release")
    print("📁 Renamed dist/ to release/")
    
    # Show final structure
    print("\n🎉 Build completed successfully!")
    print("\n📁 Release folder contents:")
    for root, dirs, files in os.walk("release"):
        level = root.replace("release", "").count(os.sep)
        indent = " " * 2 * level
        print(f"{indent}{os.path.basename(root)}/")
        subindent = " " * 2 * (level + 1)
        for file in files:
            print(f"{subindent}{file}")
    
    print(f"\n✨ Your standalone executable is ready in the 'release/' folder!")
    print("   Run it with: release/app.exe")


if __name__ == "__main__":
    main()
