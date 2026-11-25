import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import tarfile
import struct
import zipfile
import zlib


spec = importlib.util.spec_from_file_location("tesserpack_filter", Path(__file__).with_name("__main__.py"))
tesserpack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tesserpack)


def png(width, height, color, depth, rows, palette=None, transparency=None, interlace=0):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + bytes(row) for row in rows)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, interlace))
    if palette:
        data += chunk(b"PLTE", bytes(palette))
    if transparency:
        data += chunk(b"tRNS", bytes(transparency))
    return data + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def rgba_png(pixels):
    return png(len(pixels[0]), len(pixels), 6, 8, [[v for pixel in row for v in pixel] for row in pixels])


def palette_png(pixels):
    colours = sorted({pixel for row in pixels for pixel in row})
    index = {colour: i for i, colour in enumerate(colours)}
    return png(len(pixels[0]), len(pixels), 3, 8, [[index[pixel] for pixel in row] for row in pixels],
               palette=[v for colour in colours for v in colour[:3]],
               transparency=[colour[3] for colour in colours])


class TesserpackTest(unittest.TestCase):
    def test_downloads_fixed_fork_release(self):
        with tempfile.TemporaryDirectory() as temp:
            def download(url, destination):
                self.assertEqual(
                    url,
                    "https://github.com/alexdev03/TesserPack/releases/download/v0.4.7/tesserpack_Windows_x86_64.zip",
                )
                with zipfile.ZipFile(destination, "w") as archive:
                    archive.writestr("tesserpack.exe", b"binary")

            with patch.object(tesserpack.platform, "system", return_value="Windows"), \
                 patch.object(tesserpack.urllib.request, "urlretrieve", side_effect=download):
                binary = tesserpack.ensure_binary(temp, "0.4.7")

            self.assertEqual(binary.read_bytes(), b"binary")

    def test_downloads_fixed_linux_release(self):
        with tempfile.TemporaryDirectory() as temp:
            def download(url, destination):
                self.assertEqual(
                    url,
                    "https://github.com/alexdev03/TesserPack/releases/download/v0.4.7/tesserpack_Linux_x86_64.tar.gz",
                )
                with tarfile.open(destination, "w:gz") as archive:
                    entry = tarfile.TarInfo("tesserpack")
                    entry.size = len(b"binary")
                    archive.addfile(entry, io.BytesIO(b"binary"))

            with patch.object(tesserpack.platform, "system", return_value="Linux"), \
                 patch.object(tesserpack.urllib.request, "urlretrieve", side_effect=download):
                binary = tesserpack.ensure_binary(temp, "0.4.7")

            self.assertEqual(binary.read_bytes(), b"binary")

    def test_missing_png_is_restored_and_optimized_png_is_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pack = root / "RP"
            pack.mkdir()
            (pack / "missing.PNG").write_bytes(b"original missing")
            pixels = [[(1, 2, 3, 255), (4, 5, 6, 255)]]
            optimized = palette_png(pixels)
            (pack / "kept.png").write_bytes(rgba_png(pixels))

            def compile_pack(cmd, **kwargs):
                with zipfile.ZipFile(cmd[cmd.index("--out") + 1], "w") as archive:
                    archive.writestr("kept.png", optimized)
                return type("Result", (), {"returncode": 0})()

            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(os.environ, {"ROOT_DIR": str(root)}), \
                     patch.object(tesserpack, "load_merged_settings", return_value={}), \
                     patch.object(tesserpack, "ensure_binary", return_value=Path("tesserpack")), \
                     patch.object(tesserpack.subprocess, "run", side_effect=compile_pack):
                    tesserpack.main()
            finally:
                os.chdir(previous)

            self.assertEqual((pack / "missing.PNG").read_bytes(), b"original missing")
            self.assertEqual((pack / "kept.png").read_bytes(), optimized)

    def test_png_with_changed_pixels_is_restored(self):
        many = [[(x, y, (x * y) & 0xFF, 255) for x in range(20)] for y in range(20)]
        quantized = [[(x & ~3, y & ~3, ((x * y) & 0xFF) & ~63, 255) for x in range(20)] for y in range(20)]
        few = [[(x * 10, 0, 0, 255 if x else 0) for x in range(8)] for _ in range(8)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pack = root / "RP"
            pack.mkdir()
            original_many = rgba_png(many)
            optimized_few = palette_png(few)
            (pack / "spider_eggs.png").write_bytes(original_many)
            (pack / "few.png").write_bytes(rgba_png(few))

            def compile_pack(cmd, **kwargs):
                with zipfile.ZipFile(cmd[cmd.index("--out") + 1], "w") as archive:
                    archive.writestr("spider_eggs.png", palette_png(quantized))
                    archive.writestr("few.png", optimized_few)
                return type("Result", (), {"returncode": 0})()

            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(os.environ, {"ROOT_DIR": str(root)}), \
                     patch.object(tesserpack, "load_merged_settings", return_value={}), \
                     patch.object(tesserpack, "ensure_binary", return_value=Path("tesserpack")), \
                     patch.object(tesserpack.subprocess, "run", side_effect=compile_pack):
                    tesserpack.main()
            finally:
                os.chdir(previous)

            self.assertEqual((pack / "spider_eggs.png").read_bytes(), original_many)
            self.assertEqual((pack / "few.png").read_bytes(), optimized_few)

    def test_decodes_png_formats(self):
        expected = [65535, 0, 0, 65535, 0, 0, 0, 0]
        cases = [
            png(2, 1, 6, 8, [[255, 0, 0, 255, 9, 9, 9, 0]]),
            png(2, 1, 2, 16, [[255, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]], transparency=[0, 0, 0, 0, 0, 0]),
            png(2, 1, 3, 1, [[0b01000000]], palette=[255, 0, 0, 0, 0, 0], transparency=[255, 0]),
        ]
        for data in cases:
            width, height, pixels = tesserpack.png_rgba(data)
            self.assertEqual((width, height), (2, 1))
            self.assertEqual(pixels[:4], expected[:4])
            self.assertEqual(pixels[7], 0)
        gray = png(3, 3, 0, 8, [[1, 2, 3], [4, 5, 6], [7, 8, 9]], interlace=0)
        self.assertEqual(tesserpack.png_rgba(gray)[2][0::4], [v * 257 for v in range(1, 10)])


if __name__ == "__main__":
    unittest.main()
