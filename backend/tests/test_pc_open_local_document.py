import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tool_domains import pc_control


class OpenLocalDocumentRoutingTests(unittest.TestCase):
    def setUp(self):
        pc_control.configure(resolve_path=lambda value: str(Path(value).resolve()), format_size=str)

    def test_generic_file_target_uses_windows_file_association(self):
        with tempfile.TemporaryDirectory() as temp:
            document = Path(temp) / "lettre.docx"
            document.write_bytes(b"PK-test")
            with patch.object(pc_control.os, "startfile") as start, patch.object(
                pc_control, "_find_app_target"
            ) as app_lookup:
                result = asyncio.run(pc_control.execute_pc_app_launch({
                    "app_name": "file", "url": str(document),
                }))

            start.assert_called_once_with(str(document))
            app_lookup.assert_not_called()
            self.assertTrue(result["success"])
            self.assertTrue(result["verified"])
            self.assertEqual(result["method"], "windows_file_association")

    def test_generic_file_target_rejects_missing_path(self):
        with patch.object(pc_control, "_find_app_target", return_value=(None, None)):
            result = asyncio.run(pc_control.execute_pc_app_launch({
                "app_name": "file", "url": r"C:\missing\lettre.docx",
            }))
        self.assertFalse(result.get("success", False))


if __name__ == "__main__":
    unittest.main()
