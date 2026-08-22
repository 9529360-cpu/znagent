from __future__ import annotations

import unittest

from agent.kernel.telegram_resident_channel import ResidentTelegramBotApiChannel


class _Client:
    pass


class TelegramResidentCheckpointTests(unittest.TestCase):
    def test_checkpoint_round_trip_only_moves_offset_forward(self):
        adapter = ResidentTelegramBotApiChannel(
            "token",
            allow_all=True,
            client=_Client(),
        )
        adapter._offset = 41
        self.assertEqual(adapter.checkpoint(), {"offset": 41})

        adapter.restore_checkpoint({"offset": 40})
        self.assertEqual(adapter.offset, 41)
        adapter.restore_checkpoint({"offset": "57"})
        self.assertEqual(adapter.offset, 57)
        adapter.restore_checkpoint({"offset": "invalid"})
        self.assertEqual(adapter.offset, 57)

    def test_inherited_config_builder_returns_resident_checkpoint_adapter(self):
        adapter = ResidentTelegramBotApiChannel.from_zn_config(
            {
                "channels": {
                    "telegram": {
                        "allow_all": True,
                    }
                }
            },
            environ={"TELEGRAM_BOT_TOKEN": "token"},
            client=_Client(),
        )
        self.assertIsInstance(adapter, ResidentTelegramBotApiChannel)
        self.assertEqual(adapter.checkpoint(), {"offset": 0})


if __name__ == "__main__":
    unittest.main()
