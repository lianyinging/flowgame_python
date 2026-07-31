"""HTML → PDF（Playwright / Chromium）。

动态代码示例::

    from html2pdf import convert, convert_html

    # URL / 本地路径
    info = convert(str(htmlPath), output=Path(robotSpace) / "out.pdf")
    result = info["output"]

    # HTML 字符串
    info = convert_html(htmlContent, output_dir=robotSpace)
    result = info["output"]
"""
from __future__ import annotations

import sys
from pathlib import Path

from src.flowgame.tools.html2pdf.converter import (
    DEFAULT_FORMAT,
    DEFAULT_MARGIN,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_WAIT_UNTIL,
    DEFAULT_WATERMARK_ANGLE,
    DEFAULT_WATERMARK_COLOR,
    DEFAULT_WATERMARK_DENSITY,
    DEFAULT_WATERMARK_FONT_SIZE,
    DEFAULT_WATERMARK_OPACITY,
    URL_OUTPUT_DIR,
    WatermarkOptions,
    clean_llm_html,
    convert,
    convert_html,
    get_default_output_dir,
    has_llm_artifacts,
    inject_base_href,
    inject_watermark,
    is_url,
    load_html_content,
    local_path_to_file_url,
    looks_like_html_document,
    main,
    output_name_from_url,
    parse_watermark_color,
    prepare_html,
    prepare_html_string,
    render_html,
    resolve_base_url,
    resolve_output_path,
    watermark_grid_size,
)

_TOOLS_DIR = Path(__file__).resolve().parent.parent


def ensure_html2pdf_import_path() -> str:
    """把 ``tools/`` 加入 ``sys.path``，使 ``from html2pdf import convert`` 可用。"""
    root = str(_TOOLS_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


ensure_html2pdf_import_path()

__all__ = [
    "DEFAULT_FORMAT",
    "DEFAULT_MARGIN",
    "DEFAULT_TIMEOUT_MS",
    "DEFAULT_WAIT_UNTIL",
    "DEFAULT_WATERMARK_ANGLE",
    "DEFAULT_WATERMARK_COLOR",
    "DEFAULT_WATERMARK_DENSITY",
    "DEFAULT_WATERMARK_FONT_SIZE",
    "DEFAULT_WATERMARK_OPACITY",
    "URL_OUTPUT_DIR",
    "WatermarkOptions",
    "clean_llm_html",
    "convert",
    "convert_html",
    "ensure_html2pdf_import_path",
    "get_default_output_dir",
    "has_llm_artifacts",
    "inject_base_href",
    "inject_watermark",
    "is_url",
    "load_html_content",
    "local_path_to_file_url",
    "looks_like_html_document",
    "main",
    "output_name_from_url",
    "parse_watermark_color",
    "prepare_html",
    "prepare_html_string",
    "render_html",
    "resolve_base_url",
    "resolve_output_path",
    "watermark_grid_size",
]
