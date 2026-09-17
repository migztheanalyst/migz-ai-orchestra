import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "core_entrypoint_smoke", ROOT / "scripts" / "core_entrypoint_smoke.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EntrypointSmokeContractTests(unittest.TestCase):
    def test_static_smoke_accepts_unavailable_native_runtime(self):
        self.assertTrue(MODULE._valid_native_state("AVAILABLE"))
        self.assertTrue(MODULE._valid_native_state("HEALTHY"))
        self.assertTrue(MODULE._valid_native_state("UNAVAILABLE"))
        self.assertFalse(MODULE._valid_native_state("BROKEN"))


if __name__ == "__main__":
    unittest.main()
