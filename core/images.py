"""图片处理：压缩 + 上传到 Supabase Storage。"""
import hashlib
import re
import unicodedata
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps

from core.config import (
    BUCKET_NAME,
    IMAGE_COMPRESSION_ENABLED,
    IMAGE_JPEG_QUALITY,
    IMAGE_MAX_SIDE,
    MAX_SOURCE_UPLOAD_MB,
    MAX_STORED_IMAGE_MB,
)
from core.db import get_supabase


def safe_name(text: str) -> str:
    """Storage 路径保持 ASCII 安全；中文名用短哈希保证稳定。"""
    original = text.strip()
    normalized = unicodedata.normalize("NFKD", original)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"\s+", "_", ascii_text)
    slug = re.sub(r"[^a-zA-Z0-9_-]", "", slug).strip("_-").lower()
    name_hash = hashlib.sha1(original.encode("utf-8")).hexdigest()[:8]
    if slug:
        return f"{slug}-{name_hash}"[:60]
    return f"user-{name_hash}"


def get_file_ext(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in [".jpg", ".jpeg", ".png", ".webp"] else ".jpg"


def compress_image_for_storage(uploaded_file) -> dict:
    original_bytes = uploaded_file.getvalue()
    original_size_mb = len(original_bytes) / 1024 / 1024

    if original_size_mb > MAX_SOURCE_UPLOAD_MB:
        raise ValueError(
            f"文件太大：{original_size_mb:.2f} MB。"
            f"原图上限是 {MAX_SOURCE_UPLOAD_MB} MB。"
        )

    if not IMAGE_COMPRESSION_ENABLED:
        if original_size_mb > MAX_STORED_IMAGE_MB:
            raise ValueError(
                f"文件太大：{original_size_mb:.2f} MB。"
                f"存储上限是 {MAX_STORED_IMAGE_MB:.1f} MB。"
            )
        return {
            "bytes": original_bytes,
            "ext": get_file_ext(uploaded_file.name),
            "mime": uploaded_file.type or "application/octet-stream",
            "size": len(original_bytes),
        }

    try:
        image = Image.open(BytesIO(original_bytes))
        image = ImageOps.exif_transpose(image)

        if IMAGE_MAX_SIDE > 0:
            resample = getattr(Image, "Resampling", Image).LANCZOS
            image.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE), resample)

        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")

        output = BytesIO()
        quality = max(40, min(IMAGE_JPEG_QUALITY, 95))
        image.save(
            output, format="JPEG", quality=quality, optimize=True, progressive=True
        )

        compressed_bytes = output.getvalue()
        stored_size_mb = len(compressed_bytes) / 1024 / 1024
        if stored_size_mb > MAX_STORED_IMAGE_MB:
            raise ValueError(
                f"压缩后仍然太大：{stored_size_mb:.2f} MB。"
                f"存储上限是 {MAX_STORED_IMAGE_MB:.1f} MB。"
                "可以降低 IMAGE_MAX_SIDE 或 IMAGE_JPEG_QUALITY。"
            )

        return {
            "bytes": compressed_bytes,
            "ext": ".jpg",
            "mime": "image/jpeg",
            "size": len(compressed_bytes),
        }

    except ValueError:
        raise
    except Exception as e:
        raise ValueError("图片压缩失败。请上传 JPG、PNG 或 WEBP 图片。") from e


def upload_image(uploaded_file, name: str, activity_date) -> dict:
    processed = compress_image_for_storage(uploaded_file)
    storage_path = (
        f"{activity_date.isoformat()}/"
        f"{safe_name(name)}-{uuid4().hex}{processed['ext']}"
    )

    get_supabase().storage.from_(BUCKET_NAME).upload(
        path=storage_path,
        file=processed["bytes"],
        file_options={"content-type": processed["mime"], "upsert": "false"},
    )

    return {
        "file_path": storage_path,
        "file_name": uploaded_file.name,
        "file_mime": processed["mime"],
        "file_size": processed["size"],
    }
