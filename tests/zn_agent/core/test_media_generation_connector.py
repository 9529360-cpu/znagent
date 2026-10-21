from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

from zn_agent.core import KernelStore
from zn_agent.core.action_execution import (
    ActionExecutionRuntime,
    ActionRequest,
)
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.approval_cards import ApprovalCardStore, ApprovalGate
from zn_agent.core.body import NativeBody
from zn_agent.core.media_generation_connector import (
    IMAGE_ACTION_ID,
    TTS_ACTION_ID,
    MediaGenerationError,
    MediaGenerationNotConfigured,
    MediaProviderConfig,
    MediaVideoNotImplemented,
    MockMediaGenerationProvider,
    OpenAICompatibleMediaProvider,
    attach_media_generation_tools,
    register_media_generation_runtime,
    verify_audio_bytes,
    verify_image_bytes,
    write_image,
    write_tts_audio,
)
from zn_agent.core.skill_evals import eval_skills_root

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"


def _approval_runtime(tmp: Path, fabric, body):
    store = ApprovalCardStore(str(tmp / "approvals.db"))
    runtime = ActionExecutionRuntime(
        fabric, body, approval_gate=ApprovalGate(store)
    )
    return runtime, store


class FakeCredentialStore:
    def __init__(self, secrets: dict):
        self._secrets = dict(secrets)

    def get(self, reference: str):
        return self._secrets.get(reference)


class FakeHttpResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, n: int = -1) -> bytes:
        data = self._payload if n is None or n < 0 else self._payload[:n]
        return data


class MockProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockMediaGenerationProvider()

    def test_capabilities(self):
        self.assertEqual(self.provider.capabilities(), ("image", "audio"))

    def test_image_bytes_are_honest_png(self):
        media = self.provider.generate_image("a red circle")
        self.assertEqual(media.kind, "image")
        self.assertEqual(media.media_format, "png")
        observed = verify_image_bytes(media.data, {"format": "png"})
        self.assertEqual(observed["width"], 64)
        self.assertEqual(observed["height"], 64)

    def test_image_is_deterministic(self):
        first = self.provider.generate_image("same prompt")
        second = self.provider.generate_image("same prompt")
        self.assertEqual(first.data, second.data)

    def test_mock_image_rejects_other_formats_explicitly(self):
        with self.assertRaises(MediaGenerationError) as ctx:
            self.provider.generate_image("x", output_format="jpeg")
        self.assertIn("only produces png", str(ctx.exception))

    def test_audio_bytes_are_honest_wav(self):
        media = self.provider.synthesize_speech(
            "hello world", response_format="wav"
        )
        self.assertEqual(media.kind, "audio")
        observed = verify_audio_bytes(media.data, {"format": "wav"})
        self.assertEqual(observed["format"], "wav")

    def test_mock_audio_rejects_other_formats_explicitly(self):
        with self.assertRaises(MediaGenerationError) as ctx:
            self.provider.synthesize_speech("x", response_format="mp3")
        self.assertIn("only produces wav", str(ctx.exception))

    def test_video_is_interface_only(self):
        with self.assertRaises(MediaVideoNotImplemented) as ctx:
            self.provider.generate_video("a short clip")
        self.assertIn("not implemented", str(ctx.exception))


class ConfigValidationTests(unittest.TestCase):
    def test_empty_name_is_explicit(self):
        with self.assertRaises(MediaGenerationError):
            MediaProviderConfig(name="")

    def test_non_http_base_url_is_explicit(self):
        with self.assertRaises(MediaGenerationError):
            MediaProviderConfig(name="x", base_url="ftp://example.com")

    def test_secret_value_as_ref_is_explicit(self):
        with self.assertRaises(MediaGenerationError):
            MediaProviderConfig(name="x", credential_ref="sk-live-abc")

    def test_timeout_bounds(self):
        with self.assertRaises(MediaGenerationError):
            MediaProviderConfig(name="x", timeout_seconds=0.5)
        with self.assertRaises(MediaGenerationError):
            MediaProviderConfig(name="x", timeout_seconds=301.0)
        MediaProviderConfig(name="x", timeout_seconds=60.0)


class NotConfiguredTests(unittest.TestCase):
    def test_no_credential_ref_is_explicit(self):
        provider = OpenAICompatibleMediaProvider(
            MediaProviderConfig(name="oai"),
            credential_store=FakeCredentialStore({}),
        )
        with self.assertRaises(MediaGenerationNotConfigured) as ctx:
            provider.generate_image("x")
        self.assertIn("not configured", str(ctx.exception))

    def test_no_credential_store_is_explicit(self):
        provider = OpenAICompatibleMediaProvider(
            MediaProviderConfig(
                name="oai", credential_ref="provider:openai-media"
            )
        )
        with self.assertRaises(MediaGenerationNotConfigured) as ctx:
            provider.synthesize_speech("x")
        self.assertIn("not configured", str(ctx.exception))

    def test_no_secret_behind_ref_is_explicit(self):
        provider = OpenAICompatibleMediaProvider(
            MediaProviderConfig(
                name="oai", credential_ref="provider:openai-media"
            ),
            credential_store=FakeCredentialStore({}),
        )
        with self.assertRaises(MediaGenerationNotConfigured) as ctx:
            provider.generate_image("x")
        self.assertIn("provider:openai-media", str(ctx.exception))

    def test_empty_prompt_never_reaches_network(self):
        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append(request)
            raise AssertionError("network must not be touched")

        import urllib.request

        provider = OpenAICompatibleMediaProvider(
            MediaProviderConfig(
                name="oai", credential_ref="provider:openai-media"
            ),
            credential_store=FakeCredentialStore(
                {"provider:openai-media": "sk-test"}
            ),
        )
        real = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(MediaGenerationError):
                provider.generate_image("   ")
            with self.assertRaises(MediaGenerationError):
                provider.synthesize_speech("")
        finally:
            urllib.request.urlopen = real
        self.assertEqual(calls, [])


class OpenAiHttpTests(unittest.TestCase):
    def setUp(self):
        import urllib.request

        self._urllib_request = urllib.request
        self._real = urllib.request.urlopen
        self.requests = []

    def _install(self, payload: bytes):
        import urllib.request

        def fake_urlopen(request, timeout=None):
            self.requests.append(request)
            return FakeHttpResponse(payload)

        self._real = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen

    def tearDown(self):
        self._urllib_request.urlopen = self._real

    def _provider(self):
        return OpenAICompatibleMediaProvider(
            MediaProviderConfig(
                name="oai", credential_ref="provider:openai-media"
            ),
            credential_store=FakeCredentialStore(
                {"provider:openai-media": "sk-test"}
            ),
        )

    def test_image_posts_openai_shape_and_decodes_b64(self):
        from zn_agent.core.media_generation_connector import _minimal_png_bytes

        png = _minimal_png_bytes()
        self._install(
            json.dumps(
                {"data": [{"b64_json": base64.b64encode(png).decode()}]},
            ).encode()
        )
        media = self._provider().generate_image(
            "a cat", size="1024x1024", output_format="png"
        )
        self.assertEqual(media.kind, "image")
        self.assertEqual(media.data, png)
        sent = json.loads(self.requests[0].data.decode())
        self.assertEqual(sent["response_format"], "b64_json")
        self.assertEqual(sent["prompt"], "a cat")
        self.assertEqual(
            self.requests[0].get_header("Authorization"), "Bearer sk-test"
        )

    def test_image_missing_b64_is_explicit(self):
        self._install(json.dumps({"data": []}).encode())
        with self.assertRaises(MediaGenerationError) as ctx:
            self._provider().generate_image("x")
        self.assertIn("b64_json", str(ctx.exception))

    def test_image_http_error_is_explicit(self):
        import urllib.request

        def fake_urlopen(request, timeout=None):
            raise HTTPError(
                request.full_url, 401, "unauthorized", {}, io.BytesIO(b"")
            )

        real = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(MediaGenerationError) as ctx:
                self._provider().generate_image("x")
        finally:
            urllib.request.urlopen = real
        self.assertIn("HTTP 401", str(ctx.exception))

    def test_image_transport_error_is_explicit(self):
        import urllib.request

        def fake_urlopen(request, timeout=None):
            raise URLError("connection refused")

        real = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(MediaGenerationError) as ctx:
                self._provider().generate_image("x")
        finally:
            urllib.request.urlopen = real
        self.assertIn("transport error", str(ctx.exception))

    def test_tts_posts_openai_shape_and_returns_audio(self):
        from zn_agent.core.media_generation_connector import _minimal_wav_bytes

        wav = _minimal_wav_bytes()
        self._install(wav)
        media = self._provider().synthesize_speech(
            "hello", voice="alloy", response_format="wav"
        )
        self.assertEqual(media.kind, "audio")
        self.assertEqual(media.data, wav)
        sent = json.loads(self.requests[0].data.decode())
        self.assertEqual(sent["input"], "hello")
        self.assertEqual(sent["voice"], "alloy")


class VerificationTests(unittest.TestCase):
    def test_non_png_fails_png_verification(self):
        with self.assertRaises(MediaGenerationError) as ctx:
            verify_image_bytes(b"not an image", {"format": "png"})
        self.assertIn("not a PNG", str(ctx.exception))

    def test_empty_bytes_fail_explicitly(self):
        with self.assertRaises(MediaGenerationError):
            verify_image_bytes(b"", {"format": "png"})
        with self.assertRaises(MediaGenerationError):
            verify_audio_bytes(b"", {"format": "mp3"})

    def test_non_wav_fails_wav_verification(self):
        with self.assertRaises(MediaGenerationError) as ctx:
            verify_audio_bytes(b"MP3DATA", {"format": "wav"})
        self.assertIn("not a WAV", str(ctx.exception))

    def test_unknown_format_is_explicit(self):
        with self.assertRaises(MediaGenerationError):
            verify_image_bytes(b"\x89PNG\r\n\x1a\nxxxx", {"format": "tiff"})
        with self.assertRaises(MediaGenerationError):
            verify_audio_bytes(b"RIFF....WAVE", {"format": "midi"})


class WritePathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.outdir = self.root / "media"
        self.outdir.mkdir()
        self.provider = MockMediaGenerationProvider()

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_image_round_trip(self):
        media = self.provider.generate_image("x")
        artifact = write_image(media, str(self.outdir), "cover.png")
        self.assertTrue(artifact.path.is_file())
        observed = verify_image_bytes(
            artifact.path.read_bytes(), {"format": "png"}
        )
        self.assertEqual(observed["width"], 64)

    def test_write_image_appends_suffix(self):
        media = self.provider.generate_image("x")
        artifact = write_image(media, str(self.outdir), "cover")
        self.assertEqual(artifact.path.suffix, ".png")

    def test_write_image_rejects_wrong_kind(self):
        media = self.provider.synthesize_speech("x", response_format="wav")
        with self.assertRaises(MediaGenerationError) as ctx:
            write_image(media, str(self.outdir), "x.png")
        self.assertIn("image bytes", str(ctx.exception))

    def test_traversal_name_is_explicit(self):
        media = self.provider.generate_image("x")
        with self.assertRaises(MediaGenerationError) as ctx:
            write_image(media, str(self.outdir), "../evil.png")
        self.assertIn("plain filename", str(ctx.exception))
        self.assertFalse((self.root / "evil.png").exists())

    def test_write_is_atomic(self):
        media = self.provider.generate_image("x")
        artifact = write_image(media, str(self.outdir), "a.png")
        leftovers = list(self.outdir.glob(".zn-media-*.tmp"))
        self.assertEqual(leftovers, [])
        self.assertTrue(artifact.path.is_file())

    def test_write_tts_audio_round_trip(self):
        media = self.provider.synthesize_speech("x", response_format="wav")
        artifact = write_tts_audio(media, str(self.outdir), "intro.wav")
        observed = verify_audio_bytes(
            artifact.path.read_bytes(), {"format": "wav"}
        )
        self.assertEqual(observed["format"], "wav")


class MediaAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.outdir = self.root / "media"
        self.outdir.mkdir()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(self.root / "kernel.db")
        )
        self.attachment = attach_media_generation_tools(
            self.fabric,
            self.body,
            provider=MockMediaGenerationProvider(),
            output_dir=str(self.outdir),
        )

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def _runtime(self):
        runtime, store = _approval_runtime(self.root, self.fabric, self.body)
        register_media_generation_runtime(
            runtime, output_dir=str(self.outdir)
        )
        return runtime, store

    def _approve(self, store):
        pending = store.pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].action_kind, "production_change")
        store.decide(pending[0].request_id, "allow_once")

    def test_both_actions_registered_with_effect_classes(self):
        for action_id in (IMAGE_ACTION_ID, TTS_ACTION_ID):
            descriptor = self.fabric.descriptor(action_id)
            self.assertIsNotNone(descriptor, action_id)
            self.assertEqual(descriptor.effect_class, "reversible_side_effect")
            self.assertIn("approval:production_change", descriptor.tags)

    def test_detach_removes_everything(self):
        self.attachment.detach()
        for action_id in (IMAGE_ACTION_ID, TTS_ACTION_ID):
            self.assertIsNone(self.fabric.descriptor(action_id))

    def test_probe_unavailable_without_output_dir(self):
        fabric = ActionFabricRegistry()
        body = NativeBody(store=KernelStore(self.root / "k2.db"))
        attachment = attach_media_generation_tools(
            fabric, body, provider=MockMediaGenerationProvider()
        )
        try:
            availability = fabric.availability(IMAGE_ACTION_ID)
            self.assertFalse(availability.available)
            self.assertIn("no output directory", availability.reason)
        finally:
            attachment.detach()
            body.store.close()

    def test_probe_unavailable_without_provider(self):
        fabric = ActionFabricRegistry()
        body = NativeBody(store=KernelStore(self.root / "k3.db"))
        attachment = attach_media_generation_tools(
            fabric, body, output_dir=str(self.outdir)
        )
        try:
            availability = fabric.availability(TTS_ACTION_ID)
            self.assertFalse(availability.available)
            self.assertIn("not configured", availability.reason)
        finally:
            attachment.detach()
            body.store.close()

    def test_image_denied_never_touches_disk_or_provider(self):
        runtime, store = self._runtime()
        target = self.outdir / "denied.png"
        execution = runtime.execute(
            ActionRequest(
                IMAGE_ACTION_ID,
                {"output_name": "denied.png", "prompt": "a cat"},
                event_id="evt-media-deny-1",
            )
        )
        self.assertFalse(execution.success)
        self.assertIn("approval_required", execution.error or "")
        pending = store.pending_requests()
        store.decide(pending[0].request_id, "deny")
        retry = runtime.execute(
            ActionRequest(
                IMAGE_ACTION_ID,
                {"output_name": "denied.png", "prompt": "a cat"},
                event_id="evt-media-deny-1",
            )
        )
        self.assertFalse(retry.success)
        self.assertFalse(target.exists())

    def test_image_allowed_generates_and_verifies(self):
        runtime, store = self._runtime()
        args = {"output_name": "approved.png", "prompt": "a cat"}
        first = runtime.execute(
            ActionRequest(IMAGE_ACTION_ID, args, event_id="evt-media-allow-1")
        )
        self.assertFalse(first.success)
        self._approve(store)
        second = runtime.execute(
            ActionRequest(IMAGE_ACTION_ID, args, event_id="evt-media-allow-1")
        )
        self.assertTrue(second.success, second.error)
        self.assertTrue(second.verification.verified, second.verification.reason)
        data = second.body_result.data
        self.assertEqual(data["tool"], "generate_image")
        self.assertTrue(Path(data["path"]).is_file())
        verification = data["verification"]
        self.assertEqual(
            verification["observed"]["width"],
            verification["expected"]["width"],
        )

    def test_tts_allowed_generates_and_verifies(self):
        runtime, store = self._runtime()
        args = {
            "output_name": "approved.wav",
            "text": "hello world",
            "format": "wav",
        }
        first = runtime.execute(
            ActionRequest(TTS_ACTION_ID, args, event_id="evt-media-tts-1")
        )
        self.assertFalse(first.success)
        self._approve(store)
        second = runtime.execute(
            ActionRequest(TTS_ACTION_ID, args, event_id="evt-media-tts-1")
        )
        self.assertTrue(second.success, second.error)
        self.assertTrue(second.verification.verified)
        self.assertTrue(Path(second.body_result.data["path"]).is_file())

    def test_write_validates_inputs_after_approval(self):
        runtime, store = self._runtime()
        args = {"output_name": "bad.png", "prompt": "   "}
        first = runtime.execute(
            ActionRequest(IMAGE_ACTION_ID, args, event_id="evt-media-bad-1")
        )
        self.assertFalse(first.success)
        self._approve(store)
        second = runtime.execute(
            ActionRequest(IMAGE_ACTION_ID, args, event_id="evt-media-bad-1")
        )
        self.assertFalse(second.success)
        self.assertFalse((self.outdir / "bad.png").exists())

    def test_replay_of_completed_write_is_refused(self):
        kind = self.fabric.descriptor(IMAGE_ACTION_ID).body_action_kind
        args = {"output_name": "once.png", "prompt": "a cat"}
        first = self.body.act(kind, event_id="evt-media-once-1", **args)
        self.assertTrue(first.success, first.error)
        second = self.body.act(kind, event_id="evt-media-once-1", **args)
        self.assertFalse(second.success)
        self.assertIn("replay refused", second.error or "")

    def test_unconfigured_provider_dispatch_is_explicit(self):
        # Without a provider the availability probe reports unavailable, so
        # the runtime refuses before any approval card: fail-closed and
        # explicit, never a silent pretend.
        fabric = ActionFabricRegistry()
        body = NativeBody(store=KernelStore(self.root / "k4.db"))
        attachment = attach_media_generation_tools(
            fabric, body, output_dir=str(self.outdir)
        )
        try:
            runtime, store = _approval_runtime(
                self.root, fabric, body
            )
            register_media_generation_runtime(
                runtime, output_dir=str(self.outdir)
            )
            execution = runtime.execute(
                ActionRequest(
                    IMAGE_ACTION_ID,
                    {"output_name": "x.png", "prompt": "a cat"},
                    event_id="evt-media-nocfg-1",
                )
            )
            self.assertFalse(execution.success)
            self.assertIn("not configured", execution.error or "")
            self.assertEqual(store.pending_requests(), [])
        finally:
            attachment.detach()
            body.store.close()

    def test_repo_media_generation_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        media = [
            item
            for item in report.tier1
            if item.skill_name == "media-generation"
        ]
        self.assertEqual(len(media), 1, report.to_dict())
        self.assertTrue(media[0].passed, media[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


if __name__ == "__main__":
    unittest.main()
