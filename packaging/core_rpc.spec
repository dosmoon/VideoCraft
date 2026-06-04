# PyInstaller spec for the VideoCraft core_rpc sidecar (P3, packaging-design.md §2.2).
#
# onedir build → dist/core_rpc/core_rpc.exe + _internal/. build_sidecar.ps1 copies
# the result into desktop/resources/sidecar/, which electron-builder bundles as an
# extraResource. Run from the repo root inside the clean base build venv:
#   python -m PyInstaller --noconfirm --clean packaging/core_rpc.spec
#
# The sidecar imports core/* and (via core_rpc.methods.load_plugins) the plugin
# trees dynamically; PyInstaller's static analysis misses those, so we collect the
# whole packages as hiddenimports.

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# SPECPATH = this spec's dir (packaging/); the repo root is its parent.
REPO = os.path.dirname(SPECPATH)  # noqa: F821  (SPECPATH injected by PyInstaller)
SRC = os.path.join(REPO, "src")

hiddenimports = (
    collect_submodules("core")
    + collect_submodules("creations")
    + collect_submodules("materials")
    + collect_submodules("core_rpc")
    # pip is bundled so `core_rpc.exe --vc-pip` can install opt-in extras at
    # runtime (sidecar_entry.py / packaging-design.md §5.3). collect_submodules
    # pulls pip._internal + its vendored deps that static analysis misses.
    + collect_submodules("pip")
    # HTTP transport (ADR-0010). uvicorn loads its protocol/loop/lifespan
    # implementations by dotted-string at runtime — static analysis misses them,
    # so collect the whole packages. fastapi/starlette are mostly static but
    # collected for safety (and to pull starlette's optional bits we touch).
    + collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
)

# Non-.py runtime data the modules read (e.g. i18n / language / catalog JSON).
# pip ships data files (vendored cacert.pem, etc.) it needs at runtime.
datas = (
    collect_data_files("core", includes=["**/*.json", "**/*.txt"])
    + collect_data_files("pip")
)

a = Analysis(
    # Entry is a wrapper that imports core_rpc.server as a package member, so the
    # sidecar's relative imports resolve under freeze (packaging/sidecar_entry.py).
    [os.path.join(REPO, "packaging", "sidecar_entry.py")],
    pathex=[REPO, SRC],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Heavy deps that are NOT in the base closure (opt-in or removed) — exclude so
    # a stray transitive reference can't drag them in. tkinter is gone post-P2.
    excludes=[
        "torch",
        "sherpa_onnx",
        "onnxruntime",
        "pandas",
        "pyarrow",
        "wandb",
        "transformers",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="core_rpc",
    console=True,  # stdout carries the VC_RPC_PORT handshake + stderr logs.
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="core_rpc",
)
