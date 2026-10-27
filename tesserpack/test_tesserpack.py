import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


spec = importlib.util.spec_from_file_location("tesserpack_filter", Path(__file__).with_name("__main__.py"))
tesserpack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tesserpack)


class TesserpackTest(unittest.TestCase):
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
