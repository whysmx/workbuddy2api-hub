#!/usr/bin/env python3
"""Build the Windows client tool; build dependencies never enter the gateway."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "agent-setup")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Build on Windows (the output is Windows x64 only).")
    import struct
    if struct.calcsize("P") != 8:
        parser.error("A 64-bit Python interpreter is required to build the x64 tool.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wb-agent-build-") as scratch:
        subprocess.run([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onefile", "--console", "--noupx", "--name", "WorkBuddy-Setup",
            "--distpath", str(output), "--workpath", str(Path(scratch) / "work"),
            "--specpath", scratch, "--paths", str(ROOT),
            "--add-data", str(ROOT / "LICENSE") + os.pathsep + ".",
            str(ROOT / "wb_agent_setup.py"),
        ], cwd=ROOT, check=True)
    exe = output / "WorkBuddy-Setup.exe"
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(digest + "  " + exe.name + "\n", encoding="ascii")
    print("Built %s (%d bytes); SHA256 %s" % (exe, exe.stat().st_size, digest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
