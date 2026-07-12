#!/usr/bin/env python3
"""Build a deployable AWS Lambda zip for the skill.

Installs the runtime dependencies (ask-sdk-core, all pure-Python -> no OS/arch
issues) into a build dir, adds our source modules, and zips everything with the
files at the archive root (so the handler is ``lambda_function.handler``).

Run with a Python that has pip (the system Python is fine):

    python tools/build_lambda.py

Produces ``skill.zip`` in the repo root. Upload it to your Lambda, or use it with
the AWS CLI (see DEPLOY.md).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAMBDA_DIR = os.path.join(ROOT, "lambda")
BUILD_DIR = os.path.join(ROOT, "build")
OUT_ZIP = os.path.join(ROOT, "skill.zip")

# Only these source modules go in (never config.py / *.example.* / secrets).
SOURCE_MODULES = ["lambda_function.py", "actions.py", "lms.py"]
EXCLUDE_DIRS = {"__pycache__", "bin"}


def run(cmd):
    print("+", " ".join(cmd))
    subprocess.check_call(cmd)


def main() -> int:
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    os.makedirs(BUILD_DIR)

    # 1) dependencies
    run([
        sys.executable, "-m", "pip", "install",
        "-r", os.path.join(LAMBDA_DIR, "requirements.txt"),
        "--target", BUILD_DIR,
        "--quiet",
    ])

    # 2) our source
    for module in SOURCE_MODULES:
        shutil.copy2(os.path.join(LAMBDA_DIR, module), BUILD_DIR)

    # 3) zip with forward-slash arcnames at the root
    if os.path.exists(OUT_ZIP):
        os.remove(OUT_ZIP)
    file_count = 0
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder, dirs, files in os.walk(BUILD_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for name in files:
                full = os.path.join(folder, name)
                arc = os.path.relpath(full, BUILD_DIR).replace(os.sep, "/")
                zf.write(full, arc)
                file_count += 1

    size_mb = os.path.getsize(OUT_ZIP) / (1024 * 1024)
    print(f"\nOK -> {OUT_ZIP}  ({file_count} file, {size_mb:.1f} MB)")
    print("Handler: lambda_function.handler   Runtime: python3.12")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
