"""Deterministic regressions for Marvin's persistent VM Lab installer."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import vm_lab_jobs  # noqa: E402


class DummyProcess:
    pid = 424242

    def __init__(self) -> None:
        self.returncode = None
        self.finished = threading.Event()

    def poll(self):
        return self.returncode

    def wait(self):
        self.finished.wait(5)
        return self.returncode


class VMLabJobsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.original_state = vm_lab_jobs.STATE_PATH
        self.original_log = vm_lab_jobs.LOG_ROOT
        self.original_results = vm_lab_jobs._RESULTS
        vm_lab_jobs.STATE_PATH = root / "state.json"
        vm_lab_jobs.LOG_ROOT = root / "logs"
        vm_lab_jobs._RESULTS = {
            "debian13": root / "debian.json",
            "windows11": root / "windows.json",
        }
        vm_lab_jobs._PROCESSES.clear()

    def tearDown(self) -> None:
        vm_lab_jobs.STATE_PATH = self.original_state
        vm_lab_jobs.LOG_ROOT = self.original_log
        vm_lab_jobs._RESULTS = self.original_results
        vm_lab_jobs._PROCESSES.clear()
        self.temporary.cleanup()

    def test_confirmation_and_profile_are_mandatory(self) -> None:
        with self.assertRaises(vm_lab_jobs.VMLabJobError):
            vm_lab_jobs.start("windows11", confirmed=False)
        with self.assertRaises(vm_lab_jobs.VMLabJobError):
            vm_lab_jobs.start("inconnu", confirmed=True)

    def test_job_is_persistent_and_reconciles_result(self) -> None:
        process = DummyProcess()
        lab = {
            "profiles": [{"id": "windows11", "iso_verified": True, "capacity_ready": True}],
            "hyperv": {"access": True}, "installation_switch": "Default Switch",
            "host_network_policy": "host_unchanged_guest_connected_only_during_installation",
        }
        with patch.object(vm_lab_jobs.vm_lab, "status", return_value=lab), patch.object(
            vm_lab_jobs.subprocess, "Popen", return_value=process
        ) as popen:
            started = vm_lab_jobs.start("windows11", confirmed=True)
        self.assertTrue(started["active"])
        self.assertEqual(started["profile"], "windows11")
        command = popen.call_args.args[0]
        self.assertIn("run-vm-lab-install.ps1", " ".join(command))
        self.assertNotIn("password", " ".join(command).casefold())

        result_path = vm_lab_jobs._RESULTS["windows11"]
        result_path.write_text(json.dumps({"status": "completed", "vm_name": "Marvin-Windows11-TestForge"}), encoding="utf-8")
        process.returncode = 0
        process.finished.set()
        deadline = time.time() + 2
        observed = vm_lab_jobs.status()
        while observed["status"] == "running" and time.time() < deadline:
            time.sleep(0.02)
            observed = vm_lab_jobs.status()
        self.assertEqual(observed["status"], "completed")
        self.assertFalse(observed["active"])
        self.assertEqual(observed["result"]["vm_name"], "Marvin-Windows11-TestForge")


if __name__ == "__main__":
    unittest.main(verbosity=2)
