"""メニュー画像の検証と無害化。

- 容量（2 MiB）・申告されたMIME・実際の形式（先頭のシグネチャとPillowの判定）・画素数（2000万）を検証する。
- EXIFの向きを反映してから再エンコードし、EXIF（位置情報を含みうる）・ICC・テキストなどのメタデータを除く。
- 画像の内容・寸法はログに残さない。
"""

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.errors import ApiError

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
JPEG_QUALITIES = (90, 85, 75, 65)

_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
_PIL_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png"}
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png"}


@dataclass(frozen=True)
class SanitizedImage:
    data: bytes
    content_type: str  # image/jpeg・image/png

    @property
    def extension(self) -> str:
        return EXTENSIONS[self.content_type]


def _too_large(message: str | None = None) -> ApiError:
    return ApiError(413, "image_too_large", message)


def _unsupported() -> ApiError:
    return ApiError(415, "unsupported_image_type")


def sanitize_image(data: bytes, declared_type: str | None) -> SanitizedImage:
    declared = (declared_type or "").split(";", 1)[0].strip().lower()
    if declared == "image/jpg":
        declared = "image/jpeg"
    if declared not in _SIGNATURES:
        raise _unsupported()
    if len(data) > MAX_IMAGE_BYTES:
        raise _too_large()
    if not data.startswith(_SIGNATURES[declared]):
        # 拡張子・MIMEだけを変えたファイル、別形式の画像
        raise _unsupported()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if _PIL_FORMATS.get(probe.format or "") != declared:
                    raise _unsupported()
                width, height = probe.size
                if width <= 0 or height <= 0:
                    raise _unsupported()
                if width * height > MAX_IMAGE_PIXELS:
                    raise _too_large("The image exceeds the 20 megapixel limit.")
                probe.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                return _encode(oriented, declared)
    except ApiError:
        raise
    except Image.DecompressionBombWarning:
        raise _too_large("The image exceeds the 20 megapixel limit.") from None
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        # 壊れた・切り詰められた画像。Pillowの例外文は記録しない
        raise _unsupported() from None


def _encode(image: Image.Image, content_type: str) -> SanitizedImage:
    """メタデータを付けずに保存し直す。結果が2 MiBを超えればJPEGは画質を下げる。"""
    if content_type == "image/png":
        out = _save(image, "PNG", optimize=True)
        if len(out) > MAX_IMAGE_BYTES:
            raise _too_large()
        return SanitizedImage(out, content_type)

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    for quality in JPEG_QUALITIES:
        out = _save(image, "JPEG", quality=quality, optimize=True)
        if len(out) <= MAX_IMAGE_BYTES:
            return SanitizedImage(out, content_type)
    raise _too_large()


def _save(image: Image.Image, fmt: str, **params) -> bytes:
    # 保存時にPillowが元の info（exif・icc_profile・テキスト）を引き継がないよう空にする。
    # 透過色だけは画素の意味に関わるため明示して残す
    clean = image.copy()
    transparency = clean.info.get("transparency")
    clean.info = {}
    if fmt == "PNG" and transparency is not None:
        params["transparency"] = transparency
    buffer = io.BytesIO()
    clean.save(buffer, fmt, **params)
    return buffer.getvalue()
