from __future__ import annotations

import unittest

from zn_agent.core.device_capability_graph import DeviceCapabilityGraph
from zn_agent.core.windows_clipboard_context import (
    NativeWindowsClipboardContextSense,
    clipboard_context_changed,
)


class WindowsClipboardContextTests(unittest.TestCase):
    def test_observation_contains_metadata_only_and_never_clipboard_content(self) -> None:
        observation = NativeWindowsClipboardContextSense(
            probe=lambda: {
                "platform_supported": True,
                "sequence_number": 42,
                "sequence_available": True,
                "unicode_text_available": True,
                "file_drop_available": False,
                "bitmap_available": False,
                "dib_available": False,
                "owner_process_id": 1234,
                "source": ("fixture-clipboard",),
            }
        ).probe()

        self.assertTrue(observation.platform_supported)
        self.assertEqual(observation.sequence_number, 42)
        self.assertTrue(observation.sequence_available)
        self.assertTrue(observation.unicode_text_available)
        self.assertFalse(observation.file_drop_available)
        self.assertFalse(observation.bitmap_available)
        self.assertFalse(observation.dib_available)
        self.assertEqual(observation.owner_process_id, 1234)
        self.assertTrue(observation.has_supported_content)
        for forbidden in ("text", "content", "files", "bitmap_bytes", "data"):
            self.assertFalse(hasattr(observation, forbidden))

    def test_sequence_zero_is_unknown_access_not_a_fake_clipboard_identity(self) -> None:
        observation = NativeWindowsClipboardContextSense(
            probe=lambda: {
                "platform_supported": True,
                "sequence_number": 0,
                "sequence_available": False,
                "unicode_text_available": False,
                "file_drop_available": False,
                "bitmap_available": False,
                "dib_available": False,
            }
        ).probe()

        self.assertFalse(observation.sequence_available)
        self.assertIsNone(observation.sequence_number)
        self.assertFalse(observation.has_supported_content)

    def test_invalid_probe_values_fail_to_unknown_without_inventing_owner(self) -> None:
        observation = NativeWindowsClipboardContextSense(
            probe=lambda: {
                "platform_supported": True,
                "sequence_number": -1,
                "sequence_available": True,
                "unicode_text_available": "yes",
                "file_drop_available": 1,
                "owner_process_id": 0,
            }
        ).probe()

        # Explicit availability without a valid sequence remains a signal that
        # the native probe claimed access, but there is no fabricated sequence.
        self.assertTrue(observation.sequence_available)
        self.assertIsNone(observation.sequence_number)
        self.assertIsNone(observation.unicode_text_available)
        self.assertIsNone(observation.file_drop_available)
        self.assertIsNone(observation.owner_process_id)
        self.assertIsNone(observation.has_supported_content)

    def test_probe_exception_degrades_to_bounded_unknown_evidence(self) -> None:
        def boom():
            raise RuntimeError("clipboard metadata unavailable")

        observation = NativeWindowsClipboardContextSense(probe=boom).probe()
        self.assertFalse(observation.sequence_available)
        self.assertIsNone(observation.sequence_number)
        self.assertIsNone(observation.unicode_text_available)
        self.assertIsNone(observation.owner_process_id)

    def test_change_detector_tracks_sequence_format_and_owner_without_observation_time(self) -> None:
        first = NativeWindowsClipboardContextSense(
            probe=lambda: {
                "platform_supported": True,
                "sequence_number": 10,
                "sequence_available": True,
                "unicode_text_available": True,
                "file_drop_available": False,
                "bitmap_available": False,
                "dib_available": False,
                "owner_process_id": 100,
            }
        ).probe()
        same = NativeWindowsClipboardContextSense(
            probe=lambda: {
                "platform_supported": True,
                "sequence_number": 10,
                "sequence_available": True,
                "unicode_text_available": True,
                "file_drop_available": False,
                "bitmap_available": False,
                "dib_available": False,
                "owner_process_id": 100,
            }
        ).probe()
        changed = NativeWindowsClipboardContextSense(
            probe=lambda: {
                "platform_supported": True,
                "sequence_number": 11,
                "sequence_available": True,
                "unicode_text_available": False,
                "file_drop_available": True,
                "bitmap_available": False,
                "dib_available": False,
                "owner_process_id": 200,
            }
        ).probe()

        self.assertFalse(clipboard_context_changed(first, same))
        self.assertTrue(clipboard_context_changed(first, changed))

    def test_device_graph_snapshot_composes_clipboard_without_new_authority(self) -> None:
        clipboard = NativeWindowsClipboardContextSense(
            probe=lambda: {
                "platform_supported": True,
                "sequence_number": 7,
                "sequence_available": True,
                "unicode_text_available": False,
                "file_drop_available": True,
                "bitmap_available": False,
                "dib_available": False,
            }
        )
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [],
            process_provider=lambda: [],
            window_provider=lambda: [],
            cache_path=None,
            inventory_ttl_seconds=0,
            clipboard_context_sense=clipboard,
        )

        direct = graph.clipboard_context()
        snapshot = graph.resident_context_snapshot(force_inventory_refresh=True)
        self.assertEqual(direct.sequence_number, 7)
        self.assertEqual(snapshot.clipboard.sequence_number, 7)
        self.assertTrue(snapshot.clipboard.file_drop_available)


if __name__ == "__main__":
    unittest.main()
