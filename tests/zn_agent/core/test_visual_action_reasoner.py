from __future__ import annotations

import unittest

from zn_agent.core.cognitive_resource import CognitiveIncrement
from zn_agent.core.visual_action_reasoner import (
    VISUAL_ACTION_RESPONSE_SCHEMA,
    GeminiVisualActionReasoner,
    VisualActionDecision,
    parse_visual_action_decision,
)


class _ImageResource:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[dict] = []

    def invoke_image(self, **kwargs):
        self.calls.append(dict(kwargs))
        return CognitiveIncrement(
            text=self.text,
            provider="gemini",
            model="gemini-test-vision",
            finish_reason="stop",
            usage={"prompt_tokens": 7, "completion_tokens": 3},
            metadata={"reasoning": "transient model thought that must not escape"},
        )


class VisualActionReasonerTests(unittest.TestCase):
    def test_tap_requires_normalized_coordinates(self) -> None:
        decision = parse_visual_action_decision(
            '{"action":"TAP","x_fraction":0.25,"y_fraction":0.75}'
        )

        self.assertEqual(decision.action, "TAP")
        self.assertEqual(decision.x_fraction, 0.25)
        self.assertEqual(decision.y_fraction, 0.75)

        for payload in (
            '{"action":"TAP","x_fraction":-0.1,"y_fraction":0.5}',
            '{"action":"TAP","x_fraction":0.5,"y_fraction":1.1}',
            '{"action":"TAP","x_fraction":null,"y_fraction":0.5}',
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_visual_action_decision(payload)

    def test_wait_and_finish_forbid_coordinates(self) -> None:
        wait = parse_visual_action_decision(
            '{"action":"WAIT","x_fraction":null,"y_fraction":null}'
        )
        finish = parse_visual_action_decision(
            '{"action":"FINISH","x_fraction":null,"y_fraction":null}'
        )

        self.assertEqual(wait, VisualActionDecision("WAIT"))
        self.assertEqual(finish, VisualActionDecision("FINISH"))

        with self.assertRaisesRegex(ValueError, "must not carry"):
            parse_visual_action_decision(
                '{"action":"WAIT","x_fraction":0.5,"y_fraction":0.5}'
            )

    def test_parser_rejects_any_fourth_action_or_freeform_shape(self) -> None:
        bad = (
            '{"action":"TYPE","x_fraction":null,"y_fraction":null}',
            '{"action":"SCROLL","x_fraction":null,"y_fraction":null}',
            '{"action":"TAP","x_fraction":0.5,"y_fraction":0.5,"tool":"shell"}',
            'prefix {"action":"WAIT","x_fraction":null,"y_fraction":null}',
            "WAIT",
        )
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_visual_action_decision(raw)

    def test_reasoner_sends_one_screenshot_one_instruction_and_static_schema(self) -> None:
        resource = _ImageResource(
            '{"action":"TAP","x_fraction":0.4,"y_fraction":0.6}'
        )
        reasoner = GeminiVisualActionReasoner(resource)
        image = b"current-screenshot-bytes"

        result = reasoner.infer(
            instruction="Click the visible Continue button",
            image_bytes=image,
            mime_type="image/png",
            step_index=2,
        )

        self.assertEqual(result.decision.action, "TAP")
        self.assertEqual(result.provider, "gemini")
        self.assertEqual(result.model, "gemini-test-vision")
        self.assertEqual(len(resource.calls), 1)
        call = resource.calls[0]
        self.assertIs(call["image_bytes"], image)
        self.assertEqual(call["mime_type"], "image/png")
        self.assertEqual(call["response_schema"], VISUAL_ACTION_RESPONSE_SCHEMA)
        self.assertIn("Current stage instruction: Click the visible Continue button", call["question"])
        self.assertIn("Stage index: 2", call["question"])
        self.assertIn("not an autonomous agent", call["context"])
        self.assertNotIn("transient model thought", repr(result))
        self.assertNotIn("Click the visible Continue button", repr(result))

    def test_reasoner_does_not_repair_invalid_model_output(self) -> None:
        resource = _ImageResource(
            '{"action":"CLICK","x_fraction":0.4,"y_fraction":0.6}'
        )
        reasoner = GeminiVisualActionReasoner(resource)

        with self.assertRaisesRegex(ValueError, "unsupported visual action"):
            reasoner.infer(
                instruction="click continue",
                image_bytes=b"img",
            )
        self.assertEqual(len(resource.calls), 1)

    def test_instruction_and_step_index_are_bounded_before_model_call(self) -> None:
        resource = _ImageResource(
            '{"action":"WAIT","x_fraction":null,"y_fraction":null}'
        )
        reasoner = GeminiVisualActionReasoner(resource)

        with self.assertRaisesRegex(ValueError, "must not be empty"):
            reasoner.infer(instruction="", image_bytes=b"img")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            reasoner.infer(
                instruction="x" * (reasoner.MAX_INSTRUCTION_CHARS + 1),
                image_bytes=b"img",
            )
        for invalid_index in (-1, 1.5, True, "2"):
            with self.subTest(step_index=invalid_index):
                with self.assertRaisesRegex(ValueError, "non-negative"):
                    reasoner.infer(
                        instruction="wait",
                        image_bytes=b"img",
                        step_index=invalid_index,
                    )
        self.assertEqual(resource.calls, [])


if __name__ == "__main__":
    unittest.main()
