"""Validated imagery must never decode a truncated tile as invented pixels."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image, ImageDraw

import murray


def image_bytes(image, format="PNG"):
    output = io.BytesIO()
    image.save(output, format=format)
    return output.getvalue()


class CtxImageryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.cache = Path(self.temporary.name)
        self.patch = patch.object(murray, "CACHE", self.cache)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temporary.cleanup()

    def test_native_jpeg_is_fully_decoded_then_cached_as_browser_safe_png(self):
        original = image_bytes(Image.new("RGB", (512, 512), (90, 110, 130)), "JPEG")
        with patch.object(murray, "_fetch", return_value=original) as fetch:
            response = murray.murray_ctx_tile(4, 5, 20)
            again = murray.murray_ctx_tile(4, 5, 20)
        self.assertEqual(response.media_type, "image/png")
        self.assertEqual(response.headers["x-imagery-fallback-level"], "4")
        self.assertEqual(response.headers["x-imagery-resolution"], "native")
        decoded, info = murray._ctx_decode(response.body)
        source, _ = murray._ctx_decode(original)
        self.assertEqual(decoded.tobytes(), source.tobytes())
        self.assertEqual(info["source_level"], "4")
        self.assertEqual(again.body, response.body)
        self.assertEqual(fetch.call_count, 1)

    def test_corrupt_png_uses_the_correct_real_parent_quadrant(self):
        parent = Image.new("RGB", (512, 512))
        draw = ImageDraw.Draw(parent)
        colours = {(0, 0): (200, 0, 0), (0, 1): (0, 200, 0),
                   (1, 0): (0, 0, 200), (1, 1): (200, 200, 0)}
        for (y, x), colour in colours.items():
            draw.rectangle((x * 256, y * 256, x * 256 + 255, y * 256 + 255), fill=colour)
        valid_parent = image_bytes(parent)
        corrupt = image_bytes(Image.new("RGB", (512, 512), "white"))[:100]
        def fetch(url, timeout):
            return valid_parent if "/tile/0/" in url else corrupt
        with patch.object(murray, "_fetch", side_effect=fetch) as download:
            for (y, x), colour in colours.items():
                response = murray.murray_ctx_tile(1, y, x)
                image, _ = murray._ctx_decode(response.body)
                self.assertEqual(image.getpixel((256, 256)), colour)
                self.assertEqual(image.getpixel((0, 0)), colour)
                self.assertEqual(image.getpixel((511, 511)), colour)
                self.assertEqual(response.headers["x-imagery-fallback-level"], "0")
                self.assertEqual(response.headers["x-imagery-resolution"], "coarser-source-crop")
            self.assertEqual(download.call_count, 5, "The validated parent is reused by sibling tiles")

    def test_recursive_fallback_reports_original_source_level(self):
        parent = image_bytes(Image.new("RGB", (512, 512), (15, 45, 75)))
        with patch.object(murray, "_fetch", side_effect=lambda url, timeout: parent if "/tile/0/" in url else b"bad"):
            result = murray.murray_ctx_tile(3, 4, 7)
        self.assertEqual(result.headers["x-imagery-fallback-level"], "0")
        image, _ = murray._ctx_decode(result.body)
        self.assertEqual(image.getpixel((100, 100)), (15, 45, 75))

    def test_broken_cache_is_replaced_only_with_verified_pixels(self):
        path = self.cache / "ctx" / "4_5_20.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"corrupt old cache")
        source = image_bytes(Image.new("RGB", (512, 512), (1, 2, 3)))
        with patch.object(murray, "_fetch", return_value=source):
            response = murray.murray_ctx_tile(4, 5, 20)
        self.assertEqual(path.read_bytes(), response.body)
        self.assertEqual(murray._ctx_decode(path.read_bytes())[0].getpixel((0, 0)), (1, 2, 3))

    def test_missing_native_and_root_tile_returns_error_not_fake_image(self):
        with patch.object(murray, "_fetch", side_effect=OSError("Source unavailable")) as fetch:
            with self.assertRaises(HTTPException) as error:
                murray.murray_ctx_tile(2, 1, 2)
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(list(self.cache.rglob("*.png")), [])

    def test_invalid_coordinates_never_fetch_upstream(self):
        with patch.object(murray, "_fetch") as fetch:
            for args in ((13, 0, 0), (-1, 0, 0), (4, 16, 0), (4, -1, 0), (4, 0, 32), (4, 0, -1)):
                with self.assertRaises(HTTPException) as error:
                    murray.murray_ctx_tile(*args)
                self.assertEqual(error.exception.status_code, 404)
            fetch.assert_not_called()

    def test_expired_coarser_cache_can_recover_to_native_source(self):
        parent = image_bytes(Image.new("RGB", (512, 512), (1, 2, 3)))
        native = image_bytes(Image.new("RGB", (512, 512), (9, 8, 7)))
        with patch.object(murray, "_fetch", side_effect=lambda url, timeout: parent if "/tile/0/" in url else b"bad"):
            first = murray.murray_ctx_tile(1, 0, 0)
        with patch.object(murray, "CTX_FALLBACK_TTL", 0), patch.object(murray, "_fetch", return_value=native):
            second = murray.murray_ctx_tile(1, 0, 0)
        self.assertEqual(first.headers["x-imagery-fallback-level"], "0")
        self.assertEqual(second.headers["x-imagery-fallback-level"], "1")
        self.assertEqual(murray._ctx_decode(second.body)[0].getpixel((0, 0)), (9, 8, 7))


if __name__ == "__main__":
    unittest.main()
