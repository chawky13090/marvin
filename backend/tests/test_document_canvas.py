import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import document_canvas


class DocumentCanvasTests(unittest.TestCase):
    def sample(self):
        return {
            "id": "test-design", "title": "Test", "width": 794, "height": 1123,
            "background": "#ffffff", "layers": [
                {"id": "rect", "type": "rect", "x": 10, "y": 20, "width": 200, "height": 80, "fill": "#334455"},
                {"id": "text", "type": "text", "x": 20, "y": 30, "width": 180, "height": 40, "text": "Document premium", "color": "#111111", "fontSize": 24, "fontWeight": 700},
            ],
        }

    def test_validation_bounds_and_safe_colors(self):
        value = self.sample()
        value["layers"][0]["x"] = -99
        value["layers"][0]["fill"] = "url(javascript:x)"
        result = document_canvas.validate_manifest(value)
        self.assertEqual(result["layers"][0]["x"], 0)
        self.assertEqual(result["layers"][0]["fill"], "#334155")

    def test_save_load_and_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(document_canvas, "_directory", return_value=Path(temp)):
                saved = document_canvas.save(self.sample())
                self.assertTrue(saved["success"])
                self.assertEqual(document_canvas.load("test-design")["title"], "Test")
                for exporter in (document_canvas.export_pdf, document_canvas.export_docx, document_canvas.export_pptx):
                    path = exporter(self.sample())
                    self.assertTrue(path.is_file())
                    self.assertGreater(path.stat().st_size, 500)

    def test_prompt_creates_bounded_editable_manifest(self):
        result = document_canvas.manifest_from_prompt("Brochure nature premium pour une entreprise locale")
        self.assertEqual(result["schema_version"], 1)
        self.assertGreaterEqual(len(result["layers"]), 4)
        self.assertTrue(all(layer["type"] in {"text", "rect", "line", "image"} for layer in result["layers"]))


if __name__ == "__main__":
    unittest.main()
