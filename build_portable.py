"""
Build a portable distribution of VideoCraft.

Creates a self-contained folder with:
  - Python embeddable runtime (no install required)
  - All pip dependencies
  - Source code (src/)
  - Launcher scripts (.bat)

Usage:
    python build_portable.py

Output:
    dist/VideoCraft-portable/   <- ready to zip and distribute
"""

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

# Import version from the package.
# This script is run from the project root, so src/ is importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src import __version__

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Default to the donor Python's version so the tkinter .pyd we copy in
# step 3b is ABI-compatible with the embed Python.  Override only if you
# know the donor and embed share an ABI (same major.minor).
_donor = sys.version_info
PYTHON_VERSION = os.environ.get(
    "VIDEOCRAFT_PYTHON_VERSION",
    f"{_donor.major}.{_donor.minor}.{_donor.micro}",
)
PYTHON_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist", f"VideoCraft-{__version__}-portable")
PYTHON_DIR = os.path.join(DIST_DIR, "python")
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# Folders / files to copy into the distribution
COPY_DIRS = ["src"]
COPY_FILES = ["requirements.txt", "LICENSE", "README.markdown"]
# keys/ is handled separately — only the README is copied, NOT actual .key files


def step(msg):
    print(f"\n{'='*60}\n  {msg}\n{'='*60}")


def download(url, dest):
    """Download a file with progress indication."""
    print(f"  Downloading {url}")
    print(f"         -> {dest}")
    urllib.request.urlretrieve(url, dest)
    print(f"  Done ({os.path.getsize(dest) / 1024 / 1024:.1f} MB)")


def main():
    # ------------------------------------------------------------------
    # 1. Clean previous build
    # ------------------------------------------------------------------
    step("1/6  Cleaning previous build")
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)
    os.makedirs(DIST_DIR, exist_ok=True)
    print(f"  Output: {DIST_DIR}")

    # ------------------------------------------------------------------
    # 2. Download & extract Python embeddable
    # ------------------------------------------------------------------
    step("2/6  Downloading Python embeddable")
    embed_zip = os.path.join(DIST_DIR, "python-embed.zip")
    download(PYTHON_EMBED_URL, embed_zip)

    os.makedirs(PYTHON_DIR, exist_ok=True)
    with zipfile.ZipFile(embed_zip, 'r') as zf:
        zf.extractall(PYTHON_DIR)
    os.remove(embed_zip)
    print(f"  Extracted to {PYTHON_DIR}")

    # ------------------------------------------------------------------
    # 3. Enable pip: uncomment "import site" in python3XX._pth
    # ------------------------------------------------------------------
    step("3/6  Enabling pip (patching ._pth file)")
    pth_files = [f for f in os.listdir(PYTHON_DIR) if f.endswith("._pth")]
    if not pth_files:
        print("  ERROR: No ._pth file found in embeddable python!")
        sys.exit(1)
    pth_path = os.path.join(PYTHON_DIR, pth_files[0])
    with open(pth_path, 'r') as f:
        content = f.read()
    # Uncomment "import site"
    content = content.replace("#import site", "import site")
    with open(pth_path, 'w') as f:
        f.write(content)
    print(f"  Patched {pth_files[0]}")

    # ------------------------------------------------------------------
    # 3b. Copy tkinter from system Python (embeddable doesn't include it)
    # ------------------------------------------------------------------
    step("3b/6  Copying tkinter from system Python")
    # Resolve the real Python installation (not the venv)
    base_exe = getattr(sys, '_base_executable', sys.executable)
    sys_python_dir = os.path.dirname(base_exe)
    # Verify DLLs/ exists at expected location
    if not os.path.isdir(os.path.join(sys_python_dir, "DLLs")):
        print(f"  ERROR: Cannot find DLLs/ under {sys_python_dir}")
        print(f"  Please run this script with the system Python, not a venv.")
        sys.exit(1)
    print(f"  System Python: {sys_python_dir}")
    tkinter_items = {
        # DLLs: _tkinter.pyd, tcl86t.dll, tk86t.dll
        "dlls": ["_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll"],
        # tkinter package
        "lib_pkg": "tkinter",
        # tcl/tk data directories
        "tcl_dirs": ["tcl8.6", "tk8.6", "tcl8"],
    }

    # Copy DLLs
    sys_dlls = os.path.join(sys_python_dir, "DLLs")
    for dll in tkinter_items["dlls"]:
        src = os.path.join(sys_dlls, dll)
        if os.path.exists(src):
            shutil.copy2(src, PYTHON_DIR)
            print(f"  {dll}")
        else:
            print(f"  WARNING: {dll} not found in {sys_dlls}")

    # Copy tkinter package
    src_pkg = os.path.join(sys_python_dir, "Lib", tkinter_items["lib_pkg"])
    dst_pkg = os.path.join(PYTHON_DIR, "Lib", tkinter_items["lib_pkg"])
    if os.path.isdir(src_pkg):
        os.makedirs(os.path.join(PYTHON_DIR, "Lib"), exist_ok=True)
        shutil.copytree(src_pkg, dst_pkg)
        print(f"  Lib/tkinter/")
    else:
        print(f"  WARNING: tkinter package not found at {src_pkg}")

    # Copy tcl/tk data directories
    sys_tcl = os.path.join(sys_python_dir, "tcl")
    dst_tcl = os.path.join(PYTHON_DIR, "tcl")
    os.makedirs(dst_tcl, exist_ok=True)
    for tcl_dir in tkinter_items["tcl_dirs"]:
        src_dir = os.path.join(sys_tcl, tcl_dir)
        if os.path.isdir(src_dir):
            shutil.copytree(src_dir, os.path.join(dst_tcl, tcl_dir))
            print(f"  tcl/{tcl_dir}/")

    # Also add Lib/ to the ._pth so tkinter can be found
    with open(pth_path, 'r') as f:
        pth_content = f.read()
    if 'Lib' not in pth_content:
        with open(pth_path, 'a') as f:
            f.write('\nLib\n')
        print(f"  Added Lib to {pth_files[0]}")

    # ------------------------------------------------------------------
    # 4/6  Install pip + ensure uv availability
    # ------------------------------------------------------------------
    step("4/6  Installing pip (via get-pip.py)")
    python_exe = os.path.join(PYTHON_DIR, "python.exe")
    get_pip = os.path.join(DIST_DIR, "get-pip.py")
    download(GET_PIP_URL, get_pip)
    subprocess.check_call([python_exe, get_pip, "--no-warn-script-location"])
    os.remove(get_pip)
    # Embeddable Python lacks setuptools/wheel; install them for source builds
    subprocess.check_call([
        python_exe, "-m", "pip", "install",
        "setuptools", "wheel",
        "--no-warn-script-location", "--disable-pip-version-check",
    ])
    print("  pip + setuptools + wheel installed")

    # ------------------------------------------------------------------
    # 5/6  Install dependencies (prefer uv, fallback to pip)
    # ------------------------------------------------------------------
    step("5/6  Installing dependencies")

    # Try uv first (much faster). Fall back to pip if not available outside the build.
    uv_available = False
    try:
        subprocess.check_call(
            ["uv", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        uv_available = True
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    lock_file = os.path.join(PROJECT_ROOT, "requirements.lock")
    req_file = os.path.join(PROJECT_ROOT, "requirements.txt")

    if uv_available and os.path.exists(lock_file):
        print("  Using uv + requirements.lock")
        subprocess.check_call([
            "uv", "pip", "install",
            "--python", python_exe,
            "-r", lock_file,
        ])
    else:
        if not uv_available:
            print("  uv not found — falling back to pip + requirements.txt")
        else:
            print("  requirements.lock not found — falling back to pip + requirements.txt")
        subprocess.check_call([
            python_exe, "-m", "pip", "install",
            "-r", req_file,
            "--no-warn-script-location",
            "--disable-pip-version-check",
        ])
    print("  All dependencies installed")

    # ------------------------------------------------------------------
    # 6. Copy project files
    # ------------------------------------------------------------------
    step("6/6  Copying project files")
    for d in COPY_DIRS:
        src = os.path.join(PROJECT_ROOT, d)
        dst = os.path.join(DIST_DIR, d)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
            print(f"  {d}/")
    for f in COPY_FILES:
        src = os.path.join(PROJECT_ROOT, f)
        if os.path.isfile(src):
            shutil.copy2(src, DIST_DIR)
            print(f"  {f}")

    # Add src/ to the ._pth so local modules (project, operations, etc.) are importable
    with open(pth_path, 'r') as f:
        pth_content = f.read()
    if '../src' not in pth_content:
        with open(pth_path, 'a') as f:
            f.write('../src\n')
        print(f"  Added ../src to {pth_files[0]}")

    # Create keys/ with README only — NEVER ship actual API keys
    keys_dst = os.path.join(DIST_DIR, "keys")
    os.makedirs(keys_dst, exist_ok=True)
    keys_readme = os.path.join(PROJECT_ROOT, "keys", "README.md")
    if os.path.isfile(keys_readme):
        shutil.copy2(keys_readme, keys_dst)
    print("  keys/ (empty — no API keys shipped)")

    # ------------------------------------------------------------------
    # Create launcher scripts
    # ------------------------------------------------------------------
    create_launchers(DIST_DIR)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    total_size = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, fnames in os.walk(DIST_DIR)
        for f in fnames
    )
    step("Build complete!")
    print(f"  Output:  {DIST_DIR}")
    print(f"  Size:    {total_size / 1024 / 1024:.0f} MB")
    print(f"\n  To distribute: zip the VideoCraft-{__version__}-portable folder.")
    print(f"  Users just unzip and double-click VideoCraft.bat")


def create_launchers(dist_dir):
    """Create .bat launcher scripts."""

    # Main launcher — VideoCraftHub is the primary entry point.
    # PYTHONNOUSERSITE=1 isolates the portable Python from any pre-existing
    # %APPDATA%\Python\PythonXY\site-packages on the user's machine
    # (which would otherwise shadow our pinned deps via `import site`).
    bat = os.path.join(dist_dir, "VideoCraft.bat")
    with open(bat, 'w') as f:
        f.write('@echo off\r\n')
        f.write('title VideoCraft\r\n')
        f.write('cd /d "%~dp0"\r\n')
        f.write('set PYTHONNOUSERSITE=1\r\n')
        f.write('python\\python.exe src\\VideoCraftHub.py %*\r\n')
    print(f"  Created VideoCraft.bat  (-> VideoCraftHub.py)")

    # Standalone module launchers (each has its own __main__ entry)
    modules = {
        "SrtTools":  "SrtTools.py",
        "VideoTools": "VideoTools.py",
        "SplitVideo": "SplitVideo0.2.py",
    }
    for name, script in modules.items():
        bat_path = os.path.join(dist_dir, f"{name}.bat")
        with open(bat_path, 'w') as f:
            f.write('@echo off\r\n')
            f.write(f'title {name}\r\n')
            f.write('cd /d "%~dp0"\r\n')
            f.write('set PYTHONNOUSERSITE=1\r\n')
            f.write(f'python\\python.exe src\\{script} %*\r\n')
        print(f"  Created {name}.bat")


if __name__ == "__main__":
    main()
