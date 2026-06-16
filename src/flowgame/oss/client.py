"""Aliyun OSS upload helpers (phase 1)."""
from __future__ import annotations

import base64
import re
from typing import Any, Dict, Optional, Tuple

import requests

from src.flowgame.oss.file_types import resolve_file_type_meta

_URL_RE = re.compile(r"^https?://", re.I)
_DATA_URI_RE = re.compile(r"^data:([^;,]+)?(?:;base64)?,(.*)$", re.I | re.DOTALL)
_IMAGE_URL_KEYS = ("url", "imageUrl", "image_url", "src", "href", "content", "image", "link")


def _looks_like_url(text: str) -> bool:
    return bool(_URL_RE.match(text.strip()))


def _unwrap_image_content_shell(content: Any) -> Any:
    """image 类型：从 list/dict/JSON 字符串壳层中取出真实 URL 或二进制来源。"""
    if isinstance(content, str):
        text = content.strip()
        if text.startswith(("[", "{")):
            try:
                import json

                return _unwrap_image_content_shell(json.loads(text))
            except (ValueError, TypeError):
                pass
        return content
    if isinstance(content, list):
        if len(content) == 1:
            return _unwrap_image_content_shell(content[0])
        for item in content:
            unwrapped = _unwrap_image_content_shell(item)
            if isinstance(unwrapped, str) and _looks_like_url(unwrapped):
                return unwrapped
        return content
    if isinstance(content, dict):
        for key in _IMAGE_URL_KEYS:
            if key not in content:
                continue
            unwrapped = _unwrap_image_content_shell(content[key])
            if isinstance(unwrapped, str) and unwrapped.strip():
                return unwrapped
    return content


def _content_to_text(content: Any, file_type: str) -> str:
    normalized = _unwrap_image_content_shell(content) if file_type == "image" else content
    if isinstance(normalized, (dict, list)):
        import json

        return json.dumps(normalized, ensure_ascii=False)
    return str(normalized).strip()


def _has_extension(key: str) -> bool:
    path = key.rstrip("/").rsplit("/", 1)[-1]
    return "." in path and not path.startswith(".")


def _decode_content_bytes(content: str, file_type: str) -> Tuple[bytes, str]:
    text = (content or "").strip()
    if not text:
        raise ValueError("content 为空")

    default_ct, _ = resolve_file_type_meta(file_type)

    data_uri = _DATA_URI_RE.match(text)
    if data_uri:
        media = (data_uri.group(1) or default_ct).strip()
        payload = data_uri.group(2) or ""
        is_base64 = ";base64" in text[: data_uri.start(2)]
        raw = base64.b64decode(payload) if is_base64 else payload.encode("utf-8")
        return raw, media

    if file_type == "image" and _looks_like_url(text):
        response = requests.get(text, timeout=60)
        response.raise_for_status()
        body = response.content
        ct = response.headers.get("Content-Type") or default_ct
        return body, ct.split(";")[0].strip() + (
            "; charset=utf-8" if "charset" not in ct and ct.startswith("text/") else ""
        )

    if file_type == "json":
        # 若上游是 Object，get_parameter_values 可能已是 dict — 由调用方处理
        return text.encode("utf-8"), default_ct

    return text.encode("utf-8"), default_ct


def _normalize_object_key(
    key: str,
    file_type: str,
    prefix: str,
) -> str:
    normalized = (key or "").strip().lstrip("/")
    if not normalized:
        raise ValueError("Object Key 为空")

    if prefix:
        p = prefix.strip().lstrip("/")
        if p and not normalized.startswith(p):
            normalized = f"{p}/{normalized}".replace("//", "/")

    if not _has_extension(normalized):
        _, ext = resolve_file_type_meta(file_type)
        normalized = f"{normalized}{ext}"

    return normalized


def upload_content(
    *,
    content: Any,
    file_type: str,
    object_key: str,
    bucket: Optional[str] = None,
    settings: Any,
) -> Dict[str, Any]:
    try:
        import oss2
    except ImportError as exc:
        raise RuntimeError("未安装 oss2，请 pip install oss2") from exc

    endpoint = (settings.oss_endpoint or "").strip()
    access_key = (settings.oss_access_key_id or "").strip()
    secret_key = (settings.oss_access_key_secret or "").strip()
    bucket_name = (bucket or settings.oss_bucket or "").strip()

    if not endpoint or not access_key or not secret_key or not bucket_name:
        raise ValueError("OSS 未配置（请设置 OSS_ENDPOINT、OSS_ACCESS_KEY_ID、OSS_ACCESS_KEY_SECRET、OSS_BUCKET）")

    text = _content_to_text(content, file_type)
    body, content_type = _decode_content_bytes(text, file_type)
    key = _normalize_object_key(object_key, file_type, settings.oss_key_prefix or "")

    auth = oss2.Auth(access_key, secret_key)
    oss_bucket = oss2.Bucket(auth, endpoint, bucket_name)
    result = oss_bucket.put_object(key, body, headers={"Content-Type": content_type})

    etag = getattr(result, "etag", "") or ""
    url = _build_access_url(
        settings=settings,
        bucket_name=bucket_name,
        endpoint=endpoint,
        object_key=key,
        oss_bucket=oss_bucket,
    )

    return {
        "success": True,
        "url": url,
        "objectKey": key,
        "fileType": file_type,
        "contentType": content_type,
        "etag": etag,
        "errorMessage": "",
    }


def _build_access_url(
    *,
    settings: Any,
    bucket_name: str,
    endpoint: str,
    object_key: str,
    oss_bucket: Any,
) -> str:
    public_base = (settings.oss_public_base_url or "").strip()
    if public_base:
        return f"{public_base.rstrip('/')}/{object_key.lstrip('/')}"

    if settings.oss_public_read:
        host = endpoint.replace("https://", "").replace("http://", "").strip("/")
        if host.startswith(bucket_name + "."):
            return f"https://{host}/{object_key}"
        return f"https://{bucket_name}.{host}/{object_key}"

    expires = max(60, int(settings.oss_signed_url_expires or 3600))
    return oss_bucket.sign_url("GET", object_key, expires)
