"""html2pdf 工具测试（默认 Mock Playwright；集成测试需环境变量）。"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.flowgame.tools import html2pdf
from src.flowgame.tools.html2pdf import ensure_html2pdf_import_path

RUN_INTEGRATION = os.environ.get("RUN_PLAYWRIGHT_INTEGRATION", "").lower() in {
    "1",
    "true",
    "yes",
}


def make_sample_html(
    content: str = "<html><body><h1>Test PDF</h1></body></html>",
) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".html",
        delete=False,
        encoding="utf-8",
    )
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


def mock_playwright_context() -> tuple[MagicMock, MagicMock, MagicMock]:
    mock_page = MagicMock()
    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page
    mock_playwright = MagicMock()
    mock_playwright.chromium.launch.return_value = mock_browser
    return mock_playwright, mock_browser, mock_page


class TestImportPath(unittest.TestCase):
    def test_ensure_path_and_import(self) -> None:
        ensure_html2pdf_import_path()
        import html2pdf as short_name  # noqa: WPS433

        self.assertTrue(hasattr(short_name, "convert"))
        self.assertTrue(hasattr(short_name, "convert_html"))


class TestInputDetection(unittest.TestCase):
    def test_is_url(self) -> None:
        self.assertTrue(html2pdf.is_url("https://example.com/page.html"))
        self.assertTrue(html2pdf.is_url("http://example.com/page.html"))
        self.assertFalse(html2pdf.is_url("/tmp/page.html"))
        self.assertFalse(html2pdf.is_url("file:///tmp/page.html"))


class TestCleanLlmHtml(unittest.TestCase):
    def test_clean_html_fence(self) -> None:
        raw = "```html\n<html><body>test</body></html>\n```"
        cleaned, removed = html2pdf.clean_llm_html(raw)
        self.assertEqual(cleaned, "<html><body>test</body></html>")
        self.assertEqual(len(removed), 2)

    def test_clean_plain_html_unchanged(self) -> None:
        raw = "<html><body>ok</body></html>"
        cleaned, removed = html2pdf.clean_llm_html(raw)
        self.assertEqual(cleaned, raw)
        self.assertEqual(removed, [])


class TestInjectWatermark(unittest.TestCase):
    def test_inject_watermark_into_body(self) -> None:
        html = "<html><body><p>content</p></body></html>"
        options = html2pdf.WatermarkOptions(text="内部资料")
        result = html2pdf.inject_watermark(html, options)
        self.assertIn("pdf-watermark-layer", result)
        self.assertIn("内部资料", result)

    def test_inject_watermark_escapes_html(self) -> None:
        html = "<html><body></body></html>"
        options = html2pdf.WatermarkOptions(text="<script>alert(1)</script>")
        result = html2pdf.inject_watermark(html, options)
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)


class TestResolveOutputPath(unittest.TestCase):
    def test_resolve_local_html(self) -> None:
        html_path = make_sample_html()
        try:
            output = html2pdf.resolve_output_path(str(html_path))
            self.assertEqual(output.resolve(), html_path.with_suffix(".pdf").resolve())
        finally:
            html_path.unlink(missing_ok=True)

    def test_resolve_url_to_output_dir(self) -> None:
        output = html2pdf.resolve_output_path("https://example.com/page.html")
        self.assertEqual(output.parent, html2pdf.get_default_output_dir())
        self.assertEqual(output.name, "page.pdf")


class TestConvert(unittest.TestCase):
    @patch("playwright.sync_api.sync_playwright")
    def test_convert_local_html(self, mock_sync: MagicMock) -> None:
        mock_playwright, mock_browser, mock_page = mock_playwright_context()
        mock_sync.return_value.__enter__.return_value = mock_playwright

        html_path = make_sample_html("<html><body>local</body></html>")
        output_path = html_path.with_suffix(".pdf")
        try:
            result = html2pdf.convert(str(html_path))
            self.assertEqual(result["source_type"], "local")
            self.assertEqual(result["output"], str(output_path.resolve()))
            mock_page.set_content.assert_called_once()
            mock_page.pdf.assert_called_once()
            mock_browser.close.assert_called_once()
        finally:
            html_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)

    @patch("src.flowgame.tools.html2pdf.converter.requests.get")
    @patch("playwright.sync_api.sync_playwright")
    def test_convert_url(self, mock_sync: MagicMock, mock_get: MagicMock) -> None:
        mock_playwright, _, mock_page = mock_playwright_context()
        mock_sync.return_value.__enter__.return_value = mock_playwright
        mock_get.return_value.text = "<html><body>url</body></html>"
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.apparent_encoding = "utf-8"

        url = "https://example.com/demo.html"
        expected_output = html2pdf.get_default_output_dir() / "demo.pdf"
        try:
            result = html2pdf.convert(url)
            self.assertEqual(result["source_type"], "url")
            self.assertEqual(result["output"], str(expected_output.resolve()))
            mock_get.assert_called_once_with(url, timeout=60)
            rendered = mock_page.set_content.call_args.args[0]
            self.assertIn('href="https://example.com/"', rendered)
        finally:
            expected_output.unlink(missing_ok=True)

    @patch("playwright.sync_api.sync_playwright")
    def test_convert_html_string(self, mock_sync: MagicMock) -> None:
        mock_playwright, _, mock_page = mock_playwright_context()
        mock_sync.return_value.__enter__.return_value = mock_playwright

        with tempfile.TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "s.pdf"
            result = html2pdf.convert_html(
                "```html\n<html><body>hi</body></html>\n```",
                output=out,
                watermark="水印",
            )
            self.assertEqual(result["source_type"], "string")
            self.assertTrue(result["cleaned"])
            self.assertTrue(result["watermarked"])
            self.assertEqual(result["output"], str(out.resolve()))
            rendered = mock_page.set_content.call_args.args[0]
            self.assertIn("水印", rendered)
            self.assertNotIn("```", rendered)

    @patch("playwright.sync_api.sync_playwright")
    def test_convert_with_watermark(self, mock_sync: MagicMock) -> None:
        mock_playwright, _, mock_page = mock_playwright_context()
        mock_sync.return_value.__enter__.return_value = mock_playwright

        html_path = make_sample_html("<html><body>wm</body></html>")
        output_path = html_path.with_suffix(".pdf")
        try:
            result = html2pdf.convert(str(html_path), watermark="机密文件")
            self.assertTrue(result["watermarked"])
            rendered = mock_page.set_content.call_args.args[0]
            self.assertIn("机密文件", rendered)
        finally:
            html_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)

    def test_convert_invalid_wait_until(self) -> None:
        html_path = make_sample_html()
        try:
            with self.assertRaises(ValueError):
                html2pdf.convert(str(html_path), wait_until="invalid")
        finally:
            html_path.unlink(missing_ok=True)


class TestCLI(unittest.TestCase):
    @patch("src.flowgame.tools.html2pdf.converter.convert")
    def test_main_success(self, mock_convert: MagicMock) -> None:
        mock_convert.return_value = {
            "input": "https://example.com",
            "output": "/tmp/example.pdf",
            "source_type": "url",
            "cleaned": False,
            "removed_artifacts": [],
            "watermarked": False,
            "watermark_text": None,
            "watermark_options": None,
        }
        buffer = io.StringIO()
        with patch("sys.argv", ["converter.py", "https://example.com"]):
            with patch("sys.stdout", buffer):
                html2pdf.main()
        self.assertIn("/tmp/example.pdf", buffer.getvalue())


@unittest.skipUnless(
    RUN_INTEGRATION,
    "设置 RUN_PLAYWRIGHT_INTEGRATION=1 后运行真实 Playwright 集成测试",
)
class TestConvertIntegration(unittest.TestCase):
    def test_convert_local_html_creates_pdf(self) -> None:
        html_path = make_sample_html(
            "<html><head><meta charset='utf-8'></head>"
            "<body><h1>集成测试</h1></body></html>"
        )
        output_path = html_path.with_suffix(".pdf")
        try:
            result = html2pdf.convert(str(html_path))
            self.assertTrue(output_path.is_file())
            self.assertGreater(output_path.stat().st_size, 100)
            self.assertEqual(result["source_type"], "local")
        finally:
            html_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
