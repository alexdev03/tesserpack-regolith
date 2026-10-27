import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import tarfile
import zipfile


spec = importlib.util.spec_from_file_location("tesserpack_filter", Path(__file__).with_name("__main__.py"))
tesserpack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tesserpack)


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
            (pack / "kept.png").write_bytes(b"original kept")

            def compile_pack(cmd, **kwargs):
                with zipfile.ZipFile(cmd[cmd.index("--out") + 1], "w") as archive:
                    archive.writestr("kept.png", b"optimized")
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
            self.assertEqual((pack / "kept.png").read_bytes(), b"optimized")


if __name__ == "__main__":
    unittest.main()
