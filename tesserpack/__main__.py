"""
Regolith filter: run TesserPack compile on staged BP and RP folders,
then extract the optimized files back in-place. Fully supports Windows and Linux.
Version dynamic loading from settings in config.json is fully supported.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import subprocess
import zipfile
import platform
import tarfile
import urllib.request
from pathlib import Path

def load_merged_settings() -> dict:
    """Defaults from settings.json next to this script; optional merge from Regolith argv[1]."""
    base = Path(__file__).resolve().parent / "settings.json"
    data: dict = {}
    if base.is_file():
        with open(base, encoding="utf-8") as f:
            data = json.load(f)
    if len(sys.argv) > 1 and sys.argv[1].strip():
        try:
            override = json.loads(sys.argv[1])
            if isinstance(override, dict):
                data = {**data, **override}
        except json.JSONDecodeError:
            print("Warning: could not parse filter settings JSON from argv, using file only.")
    return data

def ensure_binary(root_dir: str, version: str) -> Path:
    system = platform.system()
    tesserpack_dir = Path(root_dir) / "tools" / "tesserpack" / f"bin-{version}"
    tesserpack_dir.mkdir(parents=True, exist_ok=True)

    if system == "Windows":
        exe_path = tesserpack_dir / "tesserpack.exe"
        if not exe_path.is_file():
            print(f"Windows TesserPack binary (v{version}) not found. Downloading...")
            zip_url = f"https://github.com/TBroz15/TesserPack/releases/download/v{version}/tesserpack_Windows_x86_64.zip"
            temp_zip = tesserpack_dir / "tesserpack.zip"
            urllib.request.urlretrieve(zip_url, temp_zip)
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(tesserpack_dir)
            temp_zip.unlink()
            print(f"Windows binary (v{version}) successfully downloaded and extracted.")
        return exe_path

    elif system == "Linux":
        bin_path = tesserpack_dir / "tesserpack"
        if not bin_path.is_file():
            print(f"Linux TesserPack binary (v{version}) not found. Downloading...")
            tar_url = f"https://github.com/TBroz15/TesserPack/releases/download/v{version}/tesserpack_Linux_x86_64.tar.gz"
            temp_tar = tesserpack_dir / "tesserpack.tar.gz"
            urllib.request.urlretrieve(tar_url, temp_tar)
            with tarfile.open(temp_tar, "r:gz") as tar_ref:
                tar_ref.extractall(tesserpack_dir)
            temp_tar.unlink()
            # Ensure it is executable
            os.chmod(bin_path, 0o755)
            print(f"Linux binary (v{version}) successfully downloaded and extracted.")
        return bin_path

    else:
        print(f"Error: Unsupported operating system: {system}")
        sys.exit(1)

def main() -> None:
    print("Running TesserPack Regolith Filter...")

    # Load settings to get dynamic version
    settings = load_merged_settings()
    version = settings.get("version", "0.4.2")
    print(f"Targeting TesserPack version: v{version}")

    # Get the root directory of the workspace from environment or fallback
    root_dir = os.environ.get("ROOT_DIR")
    if not root_dir:
        # Fallback to grandparent of the script
        root_dir = str(Path(__file__).resolve().parent.parent.parent)

    tesserpack_exe = ensure_binary(root_dir, version)

    # The current directory is the staging directory when Regolith runs the filter.
    # It contains BP and/or RP folders.
    staging_dir = Path(".")

    temp_dir = Path(root_dir) / ".regolith" / "tmp" / "tesserpack_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    folders_to_optimize = ["BP", "RP"]

    for folder_name in folders_to_optimize:
        folder_path = staging_dir / folder_name
        if not folder_path.is_dir():
            print(f"Staging folder {folder_name} not found, skipping.")
            continue

        print(f"Optimizing staging folder: {folder_name} using TesserPack...")

        # TesserPack 0.4.x drops most/all *.lang while keeping languages.json entries.
        # Preserve texts/ so marketplace validation (and in-game i18n) keep every locale.
        texts_src = folder_path / "texts"
        texts_backup = temp_dir / f"{folder_name}_texts_backup"
        if texts_backup.exists():
            shutil.rmtree(texts_backup)
        if texts_src.is_dir():
            print(f"Backing up {folder_name}/texts before TesserPack...")
            shutil.copytree(texts_src, texts_backup)

        # Temp output file for tesserpack
        temp_mcpack = temp_dir / f"{folder_name}_temp.mcpack"
        if temp_mcpack.exists():
            temp_mcpack.unlink()

        # Run tesserpack
        cmd = [
            str(tesserpack_exe),
            "compile",
            "--in", str(folder_path.resolve()),
            "--out", str(temp_mcpack.resolve()),
            "--disable-cache"
        ]

        print(f"Executing: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Exit code {result.returncode}\nStdout: {result.stdout}\nStderr: {result.stderr}")
        except Exception as e:
            if platform.system() == "Linux":
                print(f"[WARNING] TesserPack failed to run on Linux. Details: {e}")
                print("This is likely due to missing shared libraries (libvips, mozjpeg, libspng, libimagequant, or highway).")
                print(f"Skipping TesserPack optimization for {folder_name} and continuing with original staging files...")
                continue
            else:
                print(f"TesserPack failed for {folder_name}!")
                print(f"Error: {e}")
                sys.exit(1)

        print(f"Successfully compiled {folder_name} to {temp_mcpack}")

        # TesserPack can omit PNGs even when compilation succeeds.
        with zipfile.ZipFile(temp_mcpack, 'a', compression=zipfile.ZIP_DEFLATED) as zip_ref:
            archived = set(zip_ref.namelist())
            missing_pngs = 0
            for source in folder_path.rglob('*'):
                if source.is_file() and source.suffix.lower() == '.png':
                    relative = source.relative_to(folder_path).as_posix()
                    if relative not in archived:
                        zip_ref.write(source, relative)
                        missing_pngs += 1
            print(f"Restored {missing_pngs} missing PNG files to {folder_name} archive.")

        # Clear contents of staging folder (safe for symlinks/junctions)
        print(f"Clearing old files in staging {folder_name}...")
        for item in folder_path.iterdir():
            try:
                if item.is_dir() and not item.is_symlink():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as e:
                print(f"Warning: could not delete {item}: {e}")

        print(f"Extracting optimized files back to staging {folder_name}...")
        with zipfile.ZipFile(temp_mcpack, 'r') as zip_ref:
            zip_ref.extractall(folder_path)

        if texts_backup.is_dir():
            restored = folder_path / "texts"
            if restored.exists():
                shutil.rmtree(restored)
            shutil.copytree(texts_backup, restored)
            shutil.rmtree(texts_backup)
            lang_count = len(list(restored.glob("*.lang")))
            print(f"Restored {folder_name}/texts ({lang_count} .lang files) after TesserPack.")

        # Clean up temp file
        temp_mcpack.unlink()
        print(f"Optimization for {folder_name} completed.")

    # Clean up temp dir
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    print("TesserPack Regolith Filter execution finished successfully.")

if __name__ == "__main__":
    main()
