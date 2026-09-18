import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conductor"))

from process_runner import run_bounded, run_live_bounded


class ProcessRunnerTests(unittest.TestCase):
    def test_run_bounded_captures_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_bounded(
                [sys.executable, "-c", "print('OK')"],
                cwd=tmp,
                timeout=5,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "OK")
    def test_run_bounded_preserves_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(subprocess.TimeoutExpired):
                run_bounded(
                    [sys.executable, "-c", "import time; time.sleep(2)"],
                    cwd=tmp,
                    timeout=0.05,
                )

    def test_run_bounded_can_replace_environment(self):
        old = os.environ.get("MIGZ_PARENT_ONLY")
        os.environ["MIGZ_PARENT_ONLY"] = "SECRET"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = run_bounded(
                    [sys.executable, "-c", "import os; print(os.getenv('MIGZ_PARENT_ONLY', 'MISSING')); print(os.getenv('MIGZ_ONLY'))"],
                    cwd=tmp,
                    timeout=5,
                    env={"MIGZ_ONLY": "VALUE"},
                    merge_env=False,
                )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip().splitlines(), ["MISSING", "VALUE"])
        finally:
            if old is None:
                os.environ.pop("MIGZ_PARENT_ONLY", None)
            else:
                os.environ["MIGZ_PARENT_ONLY"] = old

    def test_run_live_bounded_times_out_and_returns_logs(self):
        beats = []
        with tempfile.TemporaryDirectory() as tmp:
            result = run_live_bounded(
                [sys.executable, "-c", "import time; print('START', flush=True); time.sleep(2)"],
                cwd=tmp,
                heartbeat=lambda: beats.append(True),
                timeout=0.5,
                heartbeat_interval=0.05,
                poll_interval=0.01,
            )
        self.assertEqual(result.returncode, 124)
        self.assertIn("START", result.stdout)
        self.assertTrue(beats)


    def test_run_live_bounded_terminates_if_heartbeat_raises(self):
        fake_proc = mock.Mock()
        fake_proc.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("process_runner.subprocess.Popen", return_value=fake_proc), \
             mock.patch("process_runner._terminate_process") as terminate:
            with self.assertRaisesRegex(RuntimeError, "heartbeat failed"):
                run_live_bounded(
                    ["fake-command"],
                    cwd=tmp,
                    heartbeat=lambda: (_ for _ in ()).throw(RuntimeError("heartbeat failed")),
                    timeout=5,
                    heartbeat_interval=0,
                    poll_interval=0,
                )
        terminate.assert_called_once_with(fake_proc)

    def test_run_live_bounded_merges_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_live_bounded(
                [sys.executable, "-c", "import os; print(os.environ['MIGZ_TEST'])"],
                cwd=tmp,
                heartbeat=lambda: None,
                timeout=5,
                env={"MIGZ_TEST": "VALUE"},
                poll_interval=0.01,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "VALUE")


if __name__ == "__main__":
    unittest.main()
