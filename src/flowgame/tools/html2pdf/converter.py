#!/usr/bin/env python3
"""使用 Playwright 将 HTML 转为 PDF，支持 URL、本地路径与 HTML 字符串。"""

from __future__ import annotations

import argparse
import html as html_module
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import unquote, urlparse

import requests

_PACKAGE_DIR = Path(__file__).resolve().parent

DEFAULT_FORMAT = "A4"
DEFAULT_WAIT_UNTIL = "networkidle"
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_MARGIN = {"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"}
DEFAULT_WATERMARK_OPACITY = 0.12
DEFAULT_WATERMARK_ANGLE = -45
DEFAULT_WATERMARK_FONT_SIZE = 48
DEFAULT_WATERMARK_DENSITY = 1.5
DEFAULT_WATERMARK_COLOR = "#000000"

LLM_OPEN_FENCE_RE = re.compile(
    r"^\ufeff?\s*```(?:html|htm|xhtml|xml)?\s*\r?\n?",
    re.IGNORECASE,
)
LLM_CLOSE_FENCE_RE = re.compile(r"\r?\n?\s*```\s*$")
BASE_HREF_RE = re.compile(r"<base\s+href\s*=", re.IGNORECASE)


def get_default_output_dir() -> Path:
    """默认 PDF 输出目录。

    环境变量 ``FLOWGAME_HTML2PDF_OUTPUT_DIR`` 可覆盖；
    默认：本包下 ``output/``。
    """
    raw = (os.getenv("FLOWGAME_HTML2PDF_OUTPUT_DIR") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (_PACKAGE_DIR / path).resolve()
        else:
            path = path.resolve()
    else:
        path = (_PACKAGE_DIR / "output").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


# 兼容旧测试/CLI 命名
URL_OUTPUT_DIR = get_default_output_dir()


@dataclass
class WatermarkOptions:
    """水印配置。"""

    text: str
    opacity: float = DEFAULT_WATERMARK_OPACITY
    angle: float = DEFAULT_WATERMARK_ANGLE
    font_size: int = DEFAULT_WATERMARK_FONT_SIZE
    density: float = DEFAULT_WATERMARK_DENSITY
    color: str = DEFAULT_WATERMARK_COLOR


def parse_watermark_color(color: str, opacity: float) -> str:
    """将 #RGB / #RRGGBB / rgb() 转为带透明度的 rgba()。"""
    opacity = max(0.01, min(opacity, 1.0))
    value = color.strip()

    if value.startswith("#"):
        hex_color = value[1:]
        if len(hex_color) == 3:
            hex_color = "".join(ch * 2 for ch in hex_color)
        if len(hex_color) != 6:
            raise ValueError(f"无效颜色值: {color}")
        red = int(hex_color[0:2], 16)
        green = int(hex_color[2:4], 16)
        blue = int(hex_color[4:6], 16)
        return f"rgba({red}, {green}, {blue}, {opacity})"

    rgb_match = re.match(
        r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})",
        value,
        re.IGNORECASE,
    )
    if rgb_match:
        red, green, blue = (int(rgb_match.group(i)) for i in range(1, 4))
        return f"rgba({red}, {green}, {blue}, {opacity})"

    named = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "red": (255, 0, 0),
        "gray": (128, 128, 128),
        "grey": (128, 128, 128),
        "blue": (0, 0, 255),
    }
    key = value.lower()
    if key in named:
        red, green, blue = named[key]
        return f"rgba({red}, {green}, {blue}, {opacity})"

    raise ValueError(f"不支持的颜色格式: {color}，请使用 #RRGGBB 或 rgb(r,g,b)")


def watermark_grid_size(density: float) -> tuple[int, int]:
    """根据密集度计算平铺行列数。值越大，水印越密。"""
    density = max(0.5, min(density, 5.0))
    cols = max(3, int(round(4 * density)))
    rows = max(3, int(round(6 * density)))
    return cols, rows


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def looks_like_html_document(content: str) -> bool:
    """粗判是否为 HTML 文档字符串（含可选 ```html 包裹）。"""
    text = (content or "").lstrip("\ufeff").lstrip()
    if not text:
        return False
    if text.startswith("```"):
        return True
    return text.startswith("<")


def local_path_to_file_url(path: Path) -> str:
    """本地 HTML 路径转为 file:// URL。"""
    return path.resolve().as_uri()


def output_name_from_url(url: str) -> str:
    """从 URL 推断 PDF 文件名。"""
    parsed = urlparse(url)
    name = unquote(Path(parsed.path).name)
    if name.lower().endswith((".html", ".htm")):
        return f"{Path(name).stem}.pdf"
    if name:
        return f"{Path(name).stem}.pdf"
    host = parsed.netloc.replace(":", "_") or "page"
    return f"{host}.pdf"


def resolve_output_path(source: str, *, output_dir: Optional[Path] = None) -> Path:
    """
    本地 HTML：输出到同级目录 {stem}.pdf
    URL：输出到 output_dir（默认包内 output/）/{name}.pdf
    """
    if is_url(source):
        out_dir = Path(output_dir) if output_dir else get_default_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / output_name_from_url(source)

    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")
    if path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError(f"不是 HTML 文件: {path}")
    return path.with_suffix(".pdf")


def resolve_base_url(source: str) -> str:
    """解析相对资源（css/js/图片）所需的 base URL。"""
    if is_url(source):
        if source.endswith((".html", ".htm")):
            return source.rsplit("/", 1)[0] + "/"
        return source if source.endswith("/") else source + "/"
    html_path = Path(source).expanduser().resolve()
    return html_path.parent.as_uri() + "/"


def has_llm_artifacts(content: str) -> bool:
    """检测 HTML 是否含大模型 markdown 代码块包裹。"""
    return bool(LLM_OPEN_FENCE_RE.search(content) or LLM_CLOSE_FENCE_RE.search(content))


def clean_llm_html(content: str) -> tuple[str, list[str]]:
    """
    去除大模型输出中常见的 ```html / ``` 包裹。

    返回:
        (清理后的 HTML, 被移除的标记说明列表)
    """
    removed: list[str] = []
    cleaned = content

    match = LLM_OPEN_FENCE_RE.match(cleaned)
    if match:
        removed.append("开头 markdown 代码块标记（如 ```html）")
        cleaned = cleaned[match.end() :]

    match = LLM_CLOSE_FENCE_RE.search(cleaned)
    if match:
        removed.append("结尾 markdown 代码块标记（```）")
        cleaned = cleaned[: match.start()]

    return cleaned.strip(), removed


def inject_base_href(html: str, base_url: str) -> str:
    """注入 <base href>，使 set_content 下相对路径 css/图片仍可加载。"""
    if BASE_HREF_RE.search(html):
        return html
    base_tag = f'<base href="{base_url}">'
    if re.search(r"<head[^>]*>", html, re.IGNORECASE):
        return re.sub(
            r"(<head[^>]*>)",
            rf"\1\n{base_tag}",
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    if re.search(r"<html[^>]*>", html, re.IGNORECASE):
        return re.sub(
            r"(<html[^>]*>)",
            rf"\1<head>{base_tag}</head>",
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    return f"<head>{base_tag}</head>{html}"


def inject_watermark(html: str, options: WatermarkOptions) -> str:
    """在 HTML 中注入平铺 CSS 水印层（读取内容后、渲染 PDF 前调用）。"""
    text = options.text.strip()
    if not text:
        return html

    safe_text = html_module.escape(text)
    color = parse_watermark_color(options.color, options.opacity)
    cols, rows = watermark_grid_size(options.density)
    items = "\n".join(
        f'  <div class="pdf-watermark-item">{safe_text}</div>'
        for _ in range(cols * rows)
    )
    style = f"""
<style id="pdf-watermark-style">
.pdf-watermark-layer {{
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 2147483647;
  display: grid;
  grid-template-columns: repeat({cols}, 1fr);
  grid-template-rows: repeat({rows}, 1fr);
  overflow: hidden;
}}
.pdf-watermark-item {{
  display: flex;
  align-items: center;
  justify-content: center;
  transform: rotate({options.angle}deg);
  font-size: {options.font_size}px;
  color: {color};
  white-space: nowrap;
  user-select: none;
  font-family: sans-serif;
  font-weight: bold;
  line-height: 1;
}}
@media print {{
  .pdf-watermark-layer {{
    position: fixed;
  }}
}}
</style>
"""
    markup = (
        f'{style}<div class="pdf-watermark-layer" aria-hidden="true">\n'
        f"{items}\n"
        f"</div>"
    )

    if re.search(r"</body>", html, re.IGNORECASE):
        return re.sub(
            r"</body>",
            markup + "\n</body>",
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    return html + markup


def load_html_content(source: str) -> str:
    """从 URL 或本地文件读取 HTML 文本。"""
    if is_url(source):
        resp = requests.get(source, timeout=60)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text

    html_path = Path(source).expanduser().resolve()
    if not html_path.is_file():
        raise FileNotFoundError(f"文件不存在: {html_path}")
    if html_path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError(f"不是 HTML 文件: {html_path}")
    return html_path.read_text(encoding="utf-8")


def prepare_html(
    source: str,
    *,
    watermark: Optional[WatermarkOptions] = None,
) -> tuple[str, str, list[str], bool]:
    """
    加载 HTML，清理大模型残留，再加水印。

    处理顺序：读取 → 清理 ```html → 加水印

    返回:
        (HTML 文本, base_url, 被移除的标记说明, 是否已加水印)
    """
    raw_html = load_html_content(source)
    cleaned_html, removed = clean_llm_html(raw_html)
    if not cleaned_html.lstrip().startswith("<"):
        print(
            "警告: 清理后内容不以 '<' 开头，可能不是有效 HTML",
            file=sys.stderr,
        )

    watermarked = False
    if watermark is not None and watermark.text.strip():
        cleaned_html = inject_watermark(cleaned_html, watermark)
        watermarked = True

    return cleaned_html, resolve_base_url(source), removed, watermarked


def prepare_html_string(
    html: str,
    *,
    base_url: str = "about:blank",
    watermark: Optional[WatermarkOptions] = None,
) -> tuple[str, str, list[str], bool]:
    """对 HTML 字符串做清理与水印，不经过文件系统。"""
    cleaned_html, removed = clean_llm_html(html or "")
    if not cleaned_html.lstrip().startswith("<"):
        print(
            "警告: 清理后内容不以 '<' 开头，可能不是有效 HTML",
            file=sys.stderr,
        )

    watermarked = False
    if watermark is not None and watermark.text.strip():
        cleaned_html = inject_watermark(cleaned_html, watermark)
        watermarked = True

    return cleaned_html, base_url, removed, watermarked


def render_html(html_content: str, base_url: str) -> str:
    """加水印后的 HTML 注入 base，供 Playwright 渲染。"""
    return inject_base_href(html_content, base_url)


def _build_watermark_opts(
    watermark: Optional[str],
    *,
    watermark_opacity: float,
    watermark_angle: float,
    watermark_font_size: int,
    watermark_density: float,
    watermark_color: str,
    watermark_options: Optional[WatermarkOptions],
) -> Optional[WatermarkOptions]:
    if watermark_options is not None:
        return watermark_options
    if watermark:
        return WatermarkOptions(
            text=watermark,
            opacity=watermark_opacity,
            angle=watermark_angle,
            font_size=watermark_font_size,
            density=watermark_density,
            color=watermark_color,
        )
    return None


def _render_pdf(
    renderable_html: str,
    output_path: Path,
    *,
    page_format: str,
    landscape: bool,
    print_background: bool,
    wait_until: str,
    timeout_ms: int,
) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ImportError(
            "未安装 playwright，请先执行：\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        ) from exc

    if wait_until not in {"load", "domcontentloaded", "networkidle", "commit"}:
        raise ValueError(
            f"不支持的 wait_until: {wait_until}，"
            "可选 load / domcontentloaded / networkidle / commit"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(
                renderable_html,
                wait_until=wait_until,
                timeout=timeout_ms,
            )
            page.pdf(
                path=str(output_path),
                format=page_format,
                landscape=landscape,
                print_background=print_background,
                margin=DEFAULT_MARGIN,
            )
        finally:
            browser.close()


def _result_dict(
    *,
    source: str,
    output_path: Path,
    source_type: str,
    removed: list[str],
    watermarked: bool,
    watermark_opts: Optional[WatermarkOptions],
) -> dict[str, Any]:
    return {
        "input": source,
        "output": str(output_path),
        "source_type": source_type,
        "cleaned": bool(removed),
        "removed_artifacts": removed,
        "watermarked": watermarked,
        "watermark_text": watermark_opts.text if watermarked and watermark_opts else None,
        "watermark_options": (
            {
                "text": watermark_opts.text,
                "opacity": watermark_opts.opacity,
                "angle": watermark_opts.angle,
                "font_size": watermark_opts.font_size,
                "density": watermark_opts.density,
                "color": watermark_opts.color,
            }
            if watermarked and watermark_opts
            else None
        ),
    }


def convert(
    source: str,
    *,
    output: Union[str, Path, None] = None,
    output_dir: Union[str, Path, None] = None,
    page_format: str = DEFAULT_FORMAT,
    landscape: bool = False,
    print_background: bool = True,
    wait_until: str = DEFAULT_WAIT_UNTIL,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    watermark: Optional[str] = None,
    watermark_opacity: float = DEFAULT_WATERMARK_OPACITY,
    watermark_angle: float = DEFAULT_WATERMARK_ANGLE,
    watermark_font_size: int = DEFAULT_WATERMARK_FONT_SIZE,
    watermark_density: float = DEFAULT_WATERMARK_DENSITY,
    watermark_color: str = DEFAULT_WATERMARK_COLOR,
    watermark_options: Optional[WatermarkOptions] = None,
) -> dict[str, Any]:
    """
    将 HTML（URL 或本地路径）转为 PDF。

    返回:
        {
            "input": str,
            "output": str,
            "source_type": "url"|"local",
            "cleaned": bool,
            "removed_artifacts": list[str],
            "watermarked": bool,
            "watermark_text": str | None,
            "watermark_options": dict | None,
        }
    """
    out_dir = Path(output_dir).expanduser() if output_dir else None
    if output is not None:
        output_path = Path(output).expanduser().resolve()
    else:
        output_path = resolve_output_path(source, output_dir=out_dir).resolve()

    watermark_opts = _build_watermark_opts(
        watermark,
        watermark_opacity=watermark_opacity,
        watermark_angle=watermark_angle,
        watermark_font_size=watermark_font_size,
        watermark_density=watermark_density,
        watermark_color=watermark_color,
        watermark_options=watermark_options,
    )
    html_content, base_url, removed, watermarked = prepare_html(
        source,
        watermark=watermark_opts,
    )
    renderable_html = render_html(html_content, base_url)
    source_type = "url" if is_url(source) else "local"

    _render_pdf(
        renderable_html,
        output_path,
        page_format=page_format,
        landscape=landscape,
        print_background=print_background,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
    )

    return _result_dict(
        source=source,
        output_path=output_path,
        source_type=source_type,
        removed=removed,
        watermarked=watermarked,
        watermark_opts=watermark_opts,
    )


def convert_html(
    html: str,
    *,
    output: Union[str, Path, None] = None,
    output_dir: Union[str, Path, None] = None,
    base_url: str = "about:blank",
    page_format: str = DEFAULT_FORMAT,
    landscape: bool = False,
    print_background: bool = True,
    wait_until: str = DEFAULT_WAIT_UNTIL,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    watermark: Optional[str] = None,
    watermark_opacity: float = DEFAULT_WATERMARK_OPACITY,
    watermark_angle: float = DEFAULT_WATERMARK_ANGLE,
    watermark_font_size: int = DEFAULT_WATERMARK_FONT_SIZE,
    watermark_density: float = DEFAULT_WATERMARK_DENSITY,
    watermark_color: str = DEFAULT_WATERMARK_COLOR,
    watermark_options: Optional[WatermarkOptions] = None,
) -> dict[str, Any]:
    """
    将 HTML **字符串**转为 PDF。

    ``output`` 未指定时写入 ``output_dir``（或默认 output/）下的随机文件名。
    """
    if output is not None:
        output_path = Path(output).expanduser().resolve()
    else:
        out_dir = (
            Path(output_dir).expanduser().resolve()
            if output_dir
            else get_default_output_dir()
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = (out_dir / f"{uuid.uuid4().hex}.pdf").resolve()

    watermark_opts = _build_watermark_opts(
        watermark,
        watermark_opacity=watermark_opacity,
        watermark_angle=watermark_angle,
        watermark_font_size=watermark_font_size,
        watermark_density=watermark_density,
        watermark_color=watermark_color,
        watermark_options=watermark_options,
    )
    html_content, resolved_base, removed, watermarked = prepare_html_string(
        html,
        base_url=base_url,
        watermark=watermark_opts,
    )
    renderable_html = render_html(html_content, resolved_base)

    _render_pdf(
        renderable_html,
        output_path,
        page_format=page_format,
        landscape=landscape,
        print_background=print_background,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
    )

    return _result_dict(
        source="(html-string)",
        output_path=output_path,
        source_type="string",
        removed=removed,
        watermarked=watermarked,
        watermark_opts=watermark_opts,
    )


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="HTML 转 PDF（Playwright / Chromium）")
    parser.add_argument(
        "source",
        help="HTML 的 URL、本地文件路径，或配合 --html-file 使用",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="输出 PDF 路径（默认：本地 HTML 同级；URL/字符串到 output/）",
    )
    parser.add_argument(
        "--format",
        default=DEFAULT_FORMAT,
        help=f"纸张规格，默认 {DEFAULT_FORMAT}",
    )
    parser.add_argument(
        "--landscape",
        action="store_true",
        help="横向打印",
    )
    parser.add_argument(
        "--no-background",
        action="store_true",
        help="不打印背景色与背景图",
    )
    parser.add_argument(
        "--wait-until",
        default=DEFAULT_WAIT_UNTIL,
        choices=["load", "domcontentloaded", "networkidle", "commit"],
        help=f"页面就绪条件，默认 {DEFAULT_WAIT_UNTIL}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help=f"页面加载超时（毫秒），默认 {DEFAULT_TIMEOUT_MS}",
    )
    parser.add_argument(
        "--watermark",
        help="水印文字（读取 HTML 并清理后注入，再生成 PDF）",
    )
    parser.add_argument(
        "--watermark-opacity",
        type=float,
        default=DEFAULT_WATERMARK_OPACITY,
        help=f"水印透明度 0~1，默认 {DEFAULT_WATERMARK_OPACITY}",
    )
    parser.add_argument(
        "--watermark-angle",
        type=float,
        default=DEFAULT_WATERMARK_ANGLE,
        help=f"水印旋转角度，默认 {DEFAULT_WATERMARK_ANGLE}",
    )
    parser.add_argument(
        "--watermark-font-size",
        type=int,
        default=DEFAULT_WATERMARK_FONT_SIZE,
        help=f"水印字号（px），默认 {DEFAULT_WATERMARK_FONT_SIZE}",
    )
    parser.add_argument(
        "--watermark-density",
        type=float,
        default=DEFAULT_WATERMARK_DENSITY,
        help=f"水印密集度 0.5~5，越大越密，默认 {DEFAULT_WATERMARK_DENSITY}",
    )
    parser.add_argument(
        "--watermark-color",
        default=DEFAULT_WATERMARK_COLOR,
        help=f"水印颜色 #RRGGBB / rgb(r,g,b)，默认 {DEFAULT_WATERMARK_COLOR}",
    )
    args = parser.parse_args(argv)

    try:
        result = convert(
            args.source,
            output=args.output,
            page_format=args.format,
            landscape=args.landscape,
            print_background=not args.no_background,
            wait_until=args.wait_until,
            timeout_ms=args.timeout,
            watermark=args.watermark,
            watermark_opacity=args.watermark_opacity,
            watermark_angle=args.watermark_angle,
            watermark_font_size=args.watermark_font_size,
            watermark_density=args.watermark_density,
            watermark_color=args.watermark_color,
        )
    except Exception as exc:
        print(f"转换失败: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"输入: {result['input']}")
    print(f"类型: {result['source_type']}")
    if result["cleaned"]:
        print(f"已清理: {', '.join(result['removed_artifacts'])}")
    if result["watermarked"]:
        opts = result["watermark_options"]
        print(
            f"已加水印: {opts['text']} "
            f"(密集度={opts['density']}, 角度={opts['angle']}°, "
            f"透明度={opts['opacity']}, 字号={opts['font_size']}px, "
            f"颜色={opts['color']})"
        )
    print(f"已保存: {result['output']}")


if __name__ == "__main__":
    main()
