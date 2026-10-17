"""画像の検証と無害化（app/services/images.py）。"""

import io

import pytest
from PIL import Image

from app.errors import ApiError
from app.services import images
from app.services.images import MAX_IMAGE_BYTES, sanitize_image


def encode(image: Image.Image, fmt: str, **params) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **params)
    return buffer.getvalue()


def jpeg_with_exif(orientation: int) -> bytes:
    image = Image.new("RGB", (40, 20), "white")
    exif = Image.Exif()
    exif[0x0112] = orientation  # Orientation
    exif[0x8825] = {2: (35.0, 40.0, 0.0)}  # GPS（位置情報）
    exif[0x010F] = "CameraMaker"
    return encode(image, "JPEG", exif=exif.tobytes())


def error_of(data: bytes, declared: str | None) -> ApiError:
    with pytest.raises(ApiError) as caught:
        sanitize_image(data, declared)
    return caught.value


def test_jpeg_orientation_is_applied_and_metadata_removed():
    result = sanitize_image(jpeg_with_exif(6), "image/jpeg")  # 6＝時計回りに90度
    assert result.content_type == "image/jpeg"
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.size == (20, 40)
        assert not image.getexif()
        assert "exif" not in image.info and "icc_profile" not in image.info
    assert b"CameraMaker" not in result.data


def test_png_metadata_removed_and_transparency_kept():
    from PIL import PngImagePlugin

    image = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "secret-location")
    result = sanitize_image(encode(image, "PNG", pnginfo=info), "image/png")
    assert result.content_type == "image/png" and result.extension == "png"
    assert b"secret-location" not in result.data
    with Image.open(io.BytesIO(result.data)) as out:
        assert out.mode == "RGBA" and out.getpixel((0, 0))[3] == 0


def test_declared_type_must_be_jpeg_or_png_and_match_content():
    png = encode(Image.new("RGB", (4, 4)), "PNG")
    jpeg = encode(Image.new("RGB", (4, 4)), "JPEG")
    gif = encode(Image.new("RGB", (4, 4)), "GIF")
    assert error_of(gif, "image/gif").status_code == 415
    assert error_of(png, "image/jpeg").status_code == 415  # MIMEだけを変えたファイル
    assert error_of(jpeg, "image/png").status_code == 415
    assert error_of(jpeg, None).status_code == 415
    assert error_of(b"\xff\xd8\xff" + b"not really a jpeg", "image/jpeg").code == "unsupported_image_type"
    assert sanitize_image(jpeg, "image/jpg").content_type == "image/jpeg"


def test_truncated_image_is_rejected():
    data = encode(Image.new("RGB", (64, 64), "white"), "PNG")
    assert error_of(data[: len(data) // 2], "image/png").status_code == 415


def test_size_limit_is_413():
    data = b"\xff\xd8\xff" + b"\0" * MAX_IMAGE_BYTES
    error = error_of(data, "image/jpeg")
    assert (error.status_code, error.code) == (413, "image_too_large")


def test_pixel_limit_is_413_before_decoding(monkeypatch):
    monkeypatch.setattr(images, "MAX_IMAGE_PIXELS", 99)
    error = error_of(encode(Image.new("RGB", (10, 10)), "PNG"), "image/png")
    assert (error.status_code, error.code) == (413, "image_too_large")
    assert sanitize_image(encode(Image.new("RGB", (9, 11)), "PNG"), "image/png")


def test_pixel_limit_default_is_20_megapixels():
    assert images.MAX_IMAGE_PIXELS == 20_000_000
