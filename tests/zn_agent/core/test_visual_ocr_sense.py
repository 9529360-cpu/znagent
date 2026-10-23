from __future__ import annotations

import unittest

from zn_agent.core.visual_ocr_sense import (
    LocalOcrProviderResult,
    LocalOcrProviderWord,
    WindowsLocalOcrSense,
)


class VisualOcrSenseTests(unittest.TestCase):
    def test_probe_returns_screen_relative_word_boxes_without_persisting_pixels(self):
        seen = []

        def capture(cx, cy, width, height):
            self.assertEqual((cx, cy, width, height), (0.5, 0.5, 0.25, 0.2))
            return (b"png-bytes", 1000, 800, 375, 320, 625, 480)

        def provider(payload):
            seen.append(payload)
            return LocalOcrProviderResult(
                language_tag="en-US",
                text="Open Settings",
                words=(
                    LocalOcrProviderWord("Open", 10, 20, 40, 18),
                    LocalOcrProviderWord("Settings", 60, 20, 75, 18),
                ),
            )

        sense = WindowsLocalOcrSense(provider_fn=provider, capture_fn=capture)
        observed = sense.probe(center_x_fraction=0.5, center_y_fraction=0.5)

        self.assertEqual(seen, [b"png-bytes"])
        self.assertEqual(observed.source, "windows-media-ocr")
        self.assertEqual(observed.language_tag, "en-US")
        self.assertEqual(observed.text, "Open Settings")
        self.assertFalse(observed.raw_frame_persisted)
        self.assertFalse(observed.truncated)
        self.assertEqual(
            (observed.words[0].left, observed.words[0].top, observed.words[0].right, observed.words[0].bottom),
            (385, 340, 425, 358),
        )

    def test_probe_clamps_provider_boxes_to_requested_region(self):
        sense = WindowsLocalOcrSense(
            capture_fn=lambda *_: (b"png", 200, 100, 50, 20, 150, 80),
            provider_fn=lambda payload: LocalOcrProviderResult(
                language_tag="",
                text="X",
                words=(LocalOcrProviderWord("X", 90, 50, 30, 30),),
            ),
        )
        observed = sense.probe(
            center_x_fraction=0.5,
            center_y_fraction=0.5,
            width_fraction=0.5,
            height_fraction=0.5,
        )
        self.assertEqual(
            (observed.words[0].left, observed.words[0].top, observed.words[0].right, observed.words[0].bottom),
            (140, 70, 150, 80),
        )

    def test_probe_marks_word_and_text_caps_as_truncated(self):
        words = tuple(
            LocalOcrProviderWord(f"w{i}", 1, 1, 2, 2)
            for i in range(140)
        )
        sense = WindowsLocalOcrSense(
            capture_fn=lambda *_: (b"png", 100, 100, 0, 0, 100, 100),
            provider_fn=lambda payload: LocalOcrProviderResult(
                language_tag="en-US",
                text="x" * 9000,
                words=words,
            ),
        )
        observed = sense.probe(
            center_x_fraction=0.5,
            center_y_fraction=0.5,
            width_fraction=0.5,
            height_fraction=0.5,
        )
        self.assertTrue(observed.truncated)
        self.assertEqual(len(observed.words), 128)
        self.assertEqual(len(observed.text), 8192)

    def test_probe_rejects_invalid_capture_geometry_before_provider(self):
        called = []
        sense = WindowsLocalOcrSense(
            capture_fn=lambda *_: (b"png", 100, 100, 90, 10, 110, 30),
            provider_fn=lambda payload: called.append(payload),
        )
        with self.assertRaisesRegex(ValueError, "out-of-bounds"):
            sense.probe(
                center_x_fraction=0.5,
                center_y_fraction=0.5,
                width_fraction=0.5,
                height_fraction=0.5,
            )
        self.assertEqual(called, [])

    def test_probe_reuses_visual_region_fraction_bounds(self):
        sense = WindowsLocalOcrSense(
            capture_fn=lambda *_: (b"png", 100, 100, 0, 0, 50, 50),
            provider_fn=lambda payload: LocalOcrProviderResult("", "", ()),
        )
        with self.assertRaises(ValueError):
            sense.probe(center_x_fraction=1.2, center_y_fraction=0.5)
        with self.assertRaises(ValueError):
            sense.probe(
                center_x_fraction=0.5,
                center_y_fraction=0.5,
                width_fraction=0.001,
            )


if __name__ == "__main__":
    unittest.main()
