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
import struct
import tarfile
import urllib.request
import zlib
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
            zip_url = f"https://github.com/alexdev03/TesserPack/releases/download/v{version}/tesserpack_Windows_x86_64.zip"
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
            tar_url = f"https://github.com/alexdev03/TesserPack/releases/download/v{version}/tesserpack_Linux_x86_64.tar.gz"
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

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _unfilter(raw: bytes, offset: int, width: int, height: int, bpp: int, stride: int) -> tuple[bytearray, int]:
    out = bytearray(stride * height)
    previous = bytearray(stride)
    for y in range(height):
        kind = raw[offset]
        line = bytearray(raw[offset + 1:offset + 1 + stride])
        offset += 1 + stride
        if kind == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif kind == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif kind == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = previous[i]
                c = previous[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        elif kind != 0:
            raise ValueError(f"invalid PNG filter {kind}")
        out[y * stride:(y + 1) * stride] = line
        previous = line
    return out, offset


def _samples(rows: bytes, width: int, height: int, depth: int, channels: int, stride: int) -> list[int]:
    if depth == 8:
        return [b for y in range(height) for b in rows[y * stride:y * stride + width * channels]]
    if depth == 16:
        return [int.from_bytes(rows[y * stride + i:y * stride + i + 2], "big")
                for y in range(height) for i in range(0, width * channels * 2, 2)]
    mask = (1 << depth) - 1
    values = []
    for y in range(height):
        row = rows[y * stride:(y + 1) * stride]
        for i in range(width * channels):
            bit = i * depth
            values.append((row[bit >> 3] >> (8 - depth - (bit & 7))) & mask)
    return values


def png_rgba(data: bytes) -> tuple[int, int, list[int]]:
    """Decode a PNG with the standard library into 16-bit RGBA samples."""
    if not data.startswith(_PNG_SIGNATURE):
        raise ValueError("not a PNG")
    pos, header, palette, transparency, compressed = 8, None, None, None, bytearray()
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"PLTE":
            palette = chunk
        elif kind == b"tRNS":
            transparency = chunk
        elif kind == b"IDAT":
            compressed += chunk
        elif kind == b"IEND":
            break
    if header is None:
        raise ValueError("missing IHDR")
    width, height, depth, color, _, _, interlace = header
    channels = _CHANNELS[color]
    bits = depth * channels
    bpp = max(1, bits // 8)
    raw = zlib.decompress(bytes(compressed))

    passes = _ADAM7 if interlace else ((0, 0, 1, 1),)
    samples = [0] * (width * height * channels)
    offset = 0
    for x0, y0, dx, dy in passes:
        pass_width = (width - x0 + dx - 1) // dx if width > x0 else 0
        pass_height = (height - y0 + dy - 1) // dy if height > y0 else 0
        if not pass_width or not pass_height:
            continue
        stride = (pass_width * bits + 7) // 8
        rows, offset = _unfilter(raw, offset, pass_width, pass_height, bpp, stride)
        values = _samples(rows, pass_width, pass_height, depth, channels, stride)
        for py in range(pass_height):
            for px in range(pass_width):
                source = (py * pass_width + px) * channels
                target = ((y0 + py * dy) * width + x0 + px * dx) * channels
                samples[target:target + channels] = values[source:source + channels]

    scale = 65535 // ((1 << depth) - 1)
    rgba = []
    if color == 3:
        if palette is None:
            raise ValueError("missing PLTE")
        alpha = transparency or b""
        for index in samples:
            rgba += (palette[index * 3] * 257, palette[index * 3 + 1] * 257, palette[index * 3 + 2] * 257,
                     (alpha[index] if index < len(alpha) else 255) * 257)
        return width, height, rgba
    key = struct.unpack(f">{len(transparency) // 2}H", transparency) if transparency else None
    for i in range(0, len(samples), channels):
        pixel = samples[i:i + channels]
        if color in (0, 4):
            gray = pixel[0] * scale
            alpha = pixel[1] * scale if color == 4 else 0 if key and pixel[0] == key[0] else 65535
            rgba += (gray, gray, gray, alpha)
        else:
            alpha = pixel[3] * scale if color == 6 else 0 if key and tuple(pixel) == key else 65535
            rgba += (pixel[0] * scale, pixel[1] * scale, pixel[2] * scale, alpha)
    return width, height, rgba


def same_png_pixels(original: bytes, optimized: bytes) -> bool:
    """True if both PNGs show the same RGBA pixels; fully transparent colour is ignored."""
    try:
        a, b = png_rgba(original), png_rgba(optimized)
    except Exception:
        return False
    if a[:2] != b[:2]:
        return False
    pa, pb = a[2], b[2]
    for i in range(0, len(pa), 4):
        if pa[i + 3] != pb[i + 3]:
            return False
        if pa[i + 3] and pa[i:i + 3] != pb[i:i + 3]:
            return False
    return True


def restore_pngs(archive: Path, folder_path: Path) -> tuple[int, int]:
    """Put back PNGs that TesserPack omitted or changed (e.g. palette quantization above 256 colours)."""
    sources = {
        source.relative_to(folder_path).as_posix(): source
        for source in folder_path.rglob("*")
        if source.is_file() and source.suffix.lower() == ".png"
    }
    rebuilt = archive.with_suffix(".rebuilt")
    missing = changed = 0
    with zipfile.ZipFile(archive) as old, zipfile.ZipFile(rebuilt, "w", zipfile.ZIP_DEFLATED) as new:
        for info in old.infolist():
            data = old.read(info)
            source = sources.pop(info.filename, None)
            if source is not None:
                original = source.read_bytes()
                if data != original and not same_png_pixels(original, data):
                    data = original
                    changed += 1
            new.writestr(info, data)
        for relative, source in sources.items():
            new.write(source, relative)
            missing += 1
    os.replace(rebuilt, archive)
    return missing, changed


def main() -> None:
    print("Running TesserPack Regolith Filter...")

    # Load settings to get dynamic version
    settings = load_merged_settings()
    version = settings.get("version", "0.4.8")
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

        # TesserPack can omit PNGs, and its palette output loses colours beyond 256.
        missing_pngs, changed_pngs = restore_pngs(temp_mcpack, folder_path)
        print(f"Restored {missing_pngs} missing PNG files to {folder_name} archive.")
        print(f"Restored {changed_pngs} PNG files whose pixels TesserPack changed in {folder_name}.")

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
