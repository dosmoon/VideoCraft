"""PyInstaller frozen entry point for the core_rpc sidecar (P3).

Two responsibilities:

1. Restore package context. A PyInstaller entry script runs as ``__main__`` with
   no package, so ``core_rpc/server.py``'s relative imports (``from .dispatch
   import ...``) would fail if frozen directly. Importing it here as a proper
   package member (``core_rpc.server``) keeps server.py unchanged and the dev
   ``python -m core_rpc.server`` path unaffected.

2. Dispatch ``--vc-pip``. In a frozen build ``sys.executable`` is THIS exe, not a
   Python with pip — so ``sys.executable -m pip install`` (used by the runtime
   extra installers) would just start a second sidecar that blocks on stdin
   forever (the install-hang the user hit). Instead the installers spawn
   ``core_rpc.exe --vc-pip <pip args>`` and we run the bundled pip in-process here
   and exit, never touching the stdio server. (packaging-design.md §5.3 / Fork A)
"""

import sys


def _patch_distlib_finder() -> None:
    """Let pip's vendored distlib locate its resources under PyInstaller.

    pip install → distlib.scripts (module import) calls
    distlib.resources.finder('pip._vendor.distlib'), which dispatches on the
    package's __loader__ TYPE. PyInstaller's frozen loader isn't in distlib's
    finder registry → DistlibException 'Unable to locate finder'. Register that
    loader type to a filesystem ResourceFinder: in an onedir build the distlib
    package dir physically exists under _internal (collect_data_files ships its
    data), so the finder resolves via the module's __path__. Best-effort.
    """
    try:
        import pip._vendor.distlib as distlib
        from pip._vendor.distlib import resources

        loader = getattr(distlib, "__loader__", None)
        if loader is not None:
            # register_finder(loader, maker) keys the registry on type(loader)
            # internally — pass the loader INSTANCE, not its type.
            resources.register_finder(
                loader, lambda module: resources.ResourceFinder(module)
            )
    except Exception:
        pass


def _main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "--vc-pip":
        # Run bundled pip in this frozen interpreter, then exit. Do NOT fall
        # through to the stdio server.
        import runpy

        _patch_distlib_finder()
        sys.argv = ["pip", *argv[1:]]
        try:
            runpy.run_module("pip", run_name="__main__")
        except SystemExit as exc:  # pip signals its exit code this way
            code = exc.code
            return code if isinstance(code, int) else (0 if code is None else 1)
        return 0

    from core_rpc.server import main

    return main()


if __name__ == "__main__":
    sys.exit(_main())
