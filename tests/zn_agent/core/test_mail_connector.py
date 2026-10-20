from __future__ import annotations

import imaplib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

from zn_agent.core import KernelStore
from zn_agent.core import mail_connector
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.approval_cards import ApprovalCardStore, ApprovalGate
from zn_agent.core.body import NativeBody
from zn_agent.core.credentials import CredentialStoreStatus
from zn_agent.core.mail_connector import (
    LIST_ACTION_ID,
    READ_ACTION_ID,
    SEARCH_ACTION_ID,
    SEND_ACTION_ID,
    ImapSession,
    MailAccountConfig,
    MailError,
    MailHeader,
    MailMessage,
    StdlibImapSession,
    StdlibImapTransport,
    attach_mail_tools,
    build_search_criteria,
    list_mailbox,
    parse_message_bytes,
    read_message,
    register_mail_runtime,
    search_mail,
    send_message,
)
from zn_agent.core.skill_evals import eval_skills_root

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"


def _raw_message(
    *,
    uid: str = "1",
    sender: str = "boss@example.com",
    to: str = "user@example.com",
    subject: str = "Hello",
    body: str = "Hi there",
    date: str = "Tue, 20 Oct 2026 10:00:00 +0000",
    attachment: bytes | None = None,
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = date
    message["Message-ID"] = f"<{uid}@example.com>"
    message.set_content(body)
    if attachment is not None:
        message.add_attachment(
            attachment,
            maintype="application",
            subtype="octet-stream",
            filename="report.bin",
        )
    return message.as_bytes()


class _FakeCredentialStore:
    def __init__(self, secrets: dict[str, str] | None = None):
        self._secrets = dict(secrets or {})

    def status(self):
        return CredentialStoreStatus(available=True, backend="fake")

    def get(self, reference: str):
        return self._secrets.get(reference)

    def set(self, reference: str, secret: str) -> None:
        self._secrets[reference] = secret

    def delete(self, reference: str) -> None:
        self._secrets.pop(reference, None)


class _FakeImapSession:
    def __init__(self, messages: dict[str, bytes], mailboxes=("INBOX", "Sent")):
        self._messages = dict(messages)
        self._mailboxes = list(mailboxes)
        self._selected = "INBOX"
        self.appended: list[tuple[str, bytes]] = []
        self.last_criteria: str | None = None
        self.closed = False

    def list_mailboxes(self) -> list[str]:
        return list(self._mailboxes)

    def select(self, mailbox: str) -> int:
        if mailbox not in self._mailboxes:
            raise MailError(f"no such mailbox {mailbox!r}")
        self._selected = mailbox
        return len(self._messages)

    def search(self, criteria: str) -> list[str]:
        self.last_criteria = criteria
        return sorted(self._messages, key=int)

    def fetch_header(self, uid: str) -> MailHeader:
        return self.fetch_message(uid).header

    def fetch_message(self, uid: str) -> MailMessage:
        raw = self._messages.get(uid)
        if raw is None:
            raise MailError(f"no such message {uid!r}")
        return parse_message_bytes(raw, uid=uid, mailbox=self._selected)

    def append(self, mailbox: str, raw: bytes) -> None:
        if mailbox not in self._mailboxes:
            raise MailError(f"no such mailbox {mailbox!r}")
        self.appended.append((mailbox, raw))

    def close(self) -> None:
        self.closed = True


class _FakeImapTransport:
    def __init__(self, messages: dict[str, bytes] | None = None):
        self._messages = dict(messages or {})
        self.sessions: list[_FakeImapSession] = []
        self.open_kwargs: list[dict] = []
        self.fail_open: Exception | None = None

    def open_session(self, **kwargs) -> ImapSession:
        self.open_kwargs.append(kwargs)
        if self.fail_open is not None:
            raise self.fail_open
        session = _FakeImapSession(self._messages)
        self.sessions.append(session)
        return session


class _FakeSmtpTransport:
    def __init__(self):
        self.calls: list[dict] = []
        self.response = "250 2.0.0 OK queued"
        self.failure: Exception | None = None

    def send(self, **kwargs) -> str:
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return self.response


def _config(**overrides) -> MailAccountConfig:
    values = {
        "imap_host": "imap.example.com",
        "username": "user@example.com",
        "smtp_host": "smtp.example.com",
        "credential_ref": "provider:mail",
    }
    values.update(overrides)
    return MailAccountConfig(**values)


def _store_with_secret() -> _FakeCredentialStore:
    return _FakeCredentialStore({"provider:mail": "s3cret"})


class MailConfigTests(unittest.TestCase):
    def test_valid_config_normalizes(self):
        config = _config()
        self.assertEqual(config.imap_port, 993)
        self.assertEqual(config.credential_ref, "provider:mail")

    def test_bad_host_rejected(self):
        with self.assertRaises(MailError):
            _config(imap_host="not a host!!")
        with self.assertRaises(MailError):
            _config(smtp_host="")

    def test_bad_port_rejected(self):
        with self.assertRaises(MailError):
            _config(imap_port=0)
        with self.assertRaises(MailError):
            _config(smtp_port=70000)

    def test_empty_username_rejected(self):
        with self.assertRaises(MailError):
            _config(username="  ")

    def test_bad_credential_ref_rejected(self):
        with self.assertRaises(ValueError):
            _config(credential_ref="has spaces")

    def test_timeout_bounds(self):
        with self.assertRaises(MailError):
            _config(timeout_seconds=0.5)
        self.assertEqual(_config(timeout_seconds=60).timeout_seconds, 60)


class MailParsingTests(unittest.TestCase):
    def test_plain_message_parses(self):
        raw = _raw_message()
        parsed = parse_message_bytes(raw, uid="1", mailbox="INBOX")
        self.assertEqual(parsed.header.from_addr, "boss@example.com")
        self.assertEqual(parsed.header.to_addrs, ("user@example.com",))
        self.assertEqual(parsed.header.subject, "Hello")
        self.assertEqual(parsed.text_body.strip(), "Hi there")
        self.assertEqual(
            parsed.header.date,
            datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(parsed.attachments, ())

    def test_encoded_subject_decodes(self):
        raw = _raw_message(subject="=?utf-8?b?5Lit5paH?=")
        parsed = parse_message_bytes(raw, uid="1", mailbox="INBOX")
        self.assertEqual(parsed.header.subject, "中文")

    def test_attachment_inventoried_not_returned(self):
        raw = _raw_message(attachment=b"\x00\x01\x02binary")
        parsed = parse_message_bytes(raw, uid="2", mailbox="INBOX")
        self.assertEqual(len(parsed.attachments), 1)
        item = parsed.attachments[0]
        self.assertEqual(item.filename, "report.bin")
        self.assertEqual(item.size, 9)
        self.assertNotIn("binary", parsed.text_body)

    def test_no_text_body_keeps_empty(self):
        message = EmailMessage()
        message["From"] = "a@example.com"
        message["To"] = "b@example.com"
        message["Subject"] = "image only"
        message.add_attachment(
            b"\xff\xd8", maintype="image", subtype="jpeg", filename="p.jpg"
        )
        parsed = parse_message_bytes(message.as_bytes(), uid="3", mailbox="INBOX")
        self.assertEqual(parsed.text_body, "")

    def test_unparseable_date_keeps_none(self):
        raw = _raw_message(date="not a date at all")
        parsed = parse_message_bytes(raw, uid="4", mailbox="INBOX")
        self.assertIsNone(parsed.header.date)

    def test_oversize_message_refused(self):
        with self.assertRaises(MailError) as caught:
            parse_message_bytes(b"x" * 5_000_001, uid="9", mailbox="INBOX")
        self.assertIn("exceeds", str(caught.exception))


class SearchCriteriaTests(unittest.TestCase):
    def test_empty_is_all(self):
        self.assertEqual(build_search_criteria(), "ALL")

    def test_tokens_combined_and_escaped(self):
        criteria = build_search_criteria(
            from_addr='boss"@example.com',
            subject="report",
            text="budget",
            since="2026-10-01",
            unseen_only=True,
        )
        self.assertIn("UNSEEN", criteria)
        self.assertIn('FROM "boss\\"@example.com"', criteria)
        self.assertIn('SUBJECT "report"', criteria)
        self.assertIn('TEXT "budget"', criteria)
        self.assertIn("SINCE 01-Oct-2026", criteria)

    def test_bad_since_is_explicit(self):
        with self.assertRaises(MailError):
            build_search_criteria(since="yesterday")


class MailCoreTests(unittest.TestCase):
    def setUp(self):
        self.messages = {
            "1": _raw_message(uid="1", subject="First", body="one"),
            "2": _raw_message(uid="2", subject="Second", body="two"),
            "3": _raw_message(uid="3", subject="Third", body="three"),
        }
        self.imap = _FakeImapTransport(self.messages)
        self.smtp = _FakeSmtpTransport()
        self.config = _config()
        self.store = _store_with_secret()

    def test_list_newest_first_with_limit(self):
        headers = list_mailbox(
            self.imap, self.config, self.store, mailbox="INBOX", limit=2
        )
        self.assertEqual([item.uid for item in headers], ["3", "2"])
        self.assertEqual(headers[0].subject, "Third")

    def test_list_selects_named_mailbox(self):
        headers = list_mailbox(
            self.imap, self.config, self.store, mailbox="INBOX", limit=1
        )
        self.assertEqual(headers[0].mailbox, "INBOX")

    def test_read_message_full(self):
        message = read_message(
            self.imap, self.config, self.store, mailbox="INBOX", uid="2"
        )
        self.assertEqual(message.header.subject, "Second")
        self.assertEqual(message.text_body.strip(), "two")

    def test_search_passes_criteria(self):
        search_mail(
            self.imap,
            self.config,
            self.store,
            mailbox="INBOX",
            from_addr="boss@example.com",
            unseen_only=True,
            limit=5,
        )
        session = self.imap.sessions[-1]
        self.assertIn("UNSEEN", session.last_criteria or "")
        self.assertIn('FROM "boss@example.com"', session.last_criteria or "")

    def test_not_configured_without_config(self):
        with self.assertRaises(MailError) as caught:
            list_mailbox(self.imap, None, self.store)
        self.assertIn("未配置", str(caught.exception))

    def test_not_configured_without_store(self):
        with self.assertRaises(MailError) as caught:
            list_mailbox(self.imap, self.config, None)
        self.assertIn("未配置", str(caught.exception))

    def test_not_configured_without_secret(self):
        with self.assertRaises(MailError) as caught:
            list_mailbox(self.imap, self.config, _FakeCredentialStore())
        self.assertIn("未配置", str(caught.exception))
        self.assertIn("provider:mail", str(caught.exception))

    def test_transport_failure_is_explicit(self):
        self.imap.fail_open = OSError("connection refused")
        with self.assertRaises(MailError) as caught:
            list_mailbox(self.imap, self.config, self.store)
        self.assertIn("connection refused", str(caught.exception))

    def test_password_comes_from_store(self):
        list_mailbox(self.imap, self.config, self.store, limit=1)
        self.assertEqual(self.imap.open_kwargs[-1]["password"], "s3cret")
        self.assertEqual(self.imap.open_kwargs[-1]["host"], "imap.example.com")

    def test_send_validates_before_touching_smtp(self):
        with self.assertRaises(MailError):
            send_message(
                self.smtp, self.config, self.store,
                to=["not-an-address"], subject="x", body="y",
            )
        with self.assertRaises(MailError):
            send_message(
                self.smtp, self.config, self.store,
                to=["a@example.com"], subject="  ", body="y",
            )
        with self.assertRaises(MailError):
            send_message(
                self.smtp, self.config, self.store,
                to=["a@example.com"], subject="bad\r\nHeader: x", body="y",
            )
        self.assertEqual(self.smtp.calls, [])

    def test_send_success_archives_to_sent(self):
        receipt = send_message(
            self.smtp,
            self.config,
            self.store,
            to=["friend@example.com"],
            cc=["cc@example.com"],
            bcc=["hidden@example.com"],
            subject="Plans",
            body="See you at noon",
            imap_transport=self.imap,
        )
        self.assertTrue(receipt.accepted)
        self.assertTrue(receipt.smtp_response.startswith("250"))
        self.assertTrue(receipt.archived_in_sent)
        self.assertEqual(receipt.archive_note, "")
        self.assertEqual(len(self.smtp.calls), 1)
        call = self.smtp.calls[0]
        self.assertEqual(
            call["to_addrs"],
            ("friend@example.com", "cc@example.com", "hidden@example.com"),
        )
        raw = call["raw_message"].decode("utf-8")
        self.assertIn("Subject: Plans", raw)
        self.assertNotIn("hidden@example.com", raw)
        session = self.imap.sessions[-1]
        self.assertEqual(len(session.appended), 1)
        mailbox, _ = session.appended[0]
        self.assertEqual(mailbox, "Sent")

    def test_send_without_imap_still_accepted(self):
        receipt = send_message(
            self.smtp, self.config, self.store,
            to=["a@example.com"], subject="x", body="y",
        )
        self.assertTrue(receipt.accepted)
        self.assertFalse(receipt.archived_in_sent)

    def test_send_refused_by_server_is_explicit(self):
        self.smtp.response = "550 5.1.1 mailbox unavailable"
        with self.assertRaises(MailError) as caught:
            send_message(
                self.smtp, self.config, self.store,
                to=["a@example.com"], subject="x", body="y",
                imap_transport=self.imap,
            )
        self.assertIn("did not accept", str(caught.exception))

    def test_send_transport_failure_is_explicit(self):
        self.smtp.failure = OSError("broken pipe")
        with self.assertRaises(MailError) as caught:
            send_message(
                self.smtp, self.config, self.store,
                to=["a@example.com"], subject="x", body="y",
            )
        self.assertIn("broken pipe", str(caught.exception))


class MailAttachTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(store=KernelStore(self.root / "kernel.db"))
        self.imap = _FakeImapTransport({"1": _raw_message()})
        self.smtp = _FakeSmtpTransport()
        self.config = _config()
        self.store = _store_with_secret()
        self.attachment = attach_mail_tools(
            self.fabric,
            self.body,
            config=self.config,
            imap_transport=self.imap,
            smtp_transport=self.smtp,
            credential_store=self.store,
        )

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def test_all_four_actions_registered_with_effect_classes(self):
        expectations = {
            LIST_ACTION_ID: "read_only",
            READ_ACTION_ID: "read_only",
            SEARCH_ACTION_ID: "read_only",
            SEND_ACTION_ID: "irreversible_side_effect",
        }
        for action_id, effect in expectations.items():
            descriptor = self.fabric.descriptor(action_id)
            self.assertIsNotNone(descriptor, action_id)
            self.assertEqual(descriptor.effect_class, effect)
        send_tags = self.fabric.descriptor(SEND_ACTION_ID).tags
        self.assertIn("approval:send", send_tags)

    def test_detach_removes_everything(self):
        self.attachment.detach()
        for action_id in (
            LIST_ACTION_ID,
            READ_ACTION_ID,
            SEARCH_ACTION_ID,
            SEND_ACTION_ID,
        ):
            self.assertIsNone(self.fabric.descriptor(action_id))

    def test_unconfigured_probe_reports_unavailable(self):
        fabric = ActionFabricRegistry()
        body = NativeBody(store=KernelStore(self.root / "kernel2.db"))
        attachment = attach_mail_tools(fabric, body, config=None)
        try:
            for action_id in (
                LIST_ACTION_ID,
                READ_ACTION_ID,
                SEARCH_ACTION_ID,
                SEND_ACTION_ID,
            ):
                availability = fabric.availability(action_id)
                self.assertEqual(availability.state, "unavailable")
                self.assertIn("no mail account configured", availability.reason)
        finally:
            attachment.detach()
            body.store.close()


class _FakeImapLibClient:
    """Canned stdlib imaplib client: exercises StdlibImapSession parsing."""

    def __init__(self):
        self.raw = _raw_message()
        self.appended: tuple[str, bytes] | None = None
        self.fail_login = False

    def login(self, username: str, password: str) -> None:
        assert (username, password) == ("user@example.com", "s3cret")
        if self.fail_login:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def list(self):
        return (
            "OK",
            [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Sent"'],
        )

    def select(self, mailbox: str, readonly: bool = True):
        return ("OK", [b"3"])

    def uid(self, command: str, *args):
        if command == "SEARCH":
            return ("OK", [b"1 2 3"])
        if command == "FETCH":
            uid, parts = str(args[0]), str(args[1])
            if "HEADER" in parts:
                header = self.raw.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
                spec = (
                    f"{uid} (BODY[HEADER] {{{len(header)}}} "
                    f"FLAGS (\\Seen) RFC822.SIZE {len(self.raw)})"
                ).encode()
                return ("OK", [(spec, header)])
            spec = (
                f"{uid} (BODY[] {{{len(self.raw)}}} FLAGS (\\Seen))"
            ).encode()
            return ("OK", [(spec, self.raw)])
        raise AssertionError(f"unexpected IMAP command {command}")

    def append(self, mailbox: str, flags, date_time, raw: bytes):
        self.appended = (mailbox, raw)
        return ("OK", [b"appended"])

    def close(self) -> None:
        return None

    def logout(self) -> None:
        return None


class StdlibTransportTests(unittest.TestCase):
    def _session(self, client: _FakeImapLibClient) -> StdlibImapSession:
        transport = StdlibImapTransport()
        with mock.patch.object(imaplib, "IMAP4_SSL", return_value=client):
            session = transport.open_session(
                host="imap.example.com",
                port=993,
                use_ssl=True,
                username="user@example.com",
                password="s3cret",
                timeout_seconds=5.0,
            )
        self.assertIsInstance(session, StdlibImapSession)
        return session

    def test_stdlib_session_end_to_end(self):
        client = _FakeImapLibClient()
        session = self._session(client)
        self.assertEqual(session.list_mailboxes(), ["INBOX", "Sent"])
        self.assertEqual(session.select("INBOX"), 3)
        self.assertEqual(session.search("ALL"), ["1", "2", "3"])
        header = session.fetch_header("1")
        self.assertEqual(header.subject, "Hello")
        self.assertEqual(header.from_addr, "boss@example.com")
        self.assertEqual(header.flags, ("\\Seen",))
        self.assertEqual(header.size, len(client.raw))
        message = session.fetch_message("2")
        self.assertEqual(message.header.uid, "2")
        self.assertEqual(message.text_body.strip(), "Hi there")
        session.append("Sent", b"raw-bytes")
        assert client.appended is not None
        self.assertEqual(client.appended[0], "Sent")
        session.close()

    def test_stdlib_login_failure_is_explicit(self):
        client = _FakeImapLibClient()
        client.fail_login = True
        transport = StdlibImapTransport()
        with mock.patch.object(imaplib, "IMAP4_SSL", return_value=client):
            with self.assertRaises(MailError) as caught:
                transport.open_session(
                    host="imap.example.com",
                    port=993,
                    use_ssl=True,
                    username="user@example.com",
                    password="s3cret",
                    timeout_seconds=5.0,
                )
        self.assertIn("login", str(caught.exception).lower())

    def test_stdlib_non_ok_response_is_explicit(self):
        client = _FakeImapLibClient()
        session = self._session(client)
        with mock.patch.object(
            client, "uid", return_value=("NO", [b"cannot do that"])
        ):
            with self.assertRaises(MailError) as caught:
                session.search("ALL")
        self.assertIn("SEARCH", str(caught.exception))
        session.close()


class MailApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(store=KernelStore(self.root / "kernel.db"))
        self.imap = _FakeImapTransport({"1": _raw_message()})
        self.smtp = _FakeSmtpTransport()
        self.config = _config()
        self.store = _store_with_secret()
        self.attachment = attach_mail_tools(
            self.fabric,
            self.body,
            config=self.config,
            imap_transport=self.imap,
            smtp_transport=self.smtp,
            credential_store=self.store,
        )

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def _runtime(self):
        store = ApprovalCardStore(str(self.root / "approvals.db"))
        runtime = ActionExecutionRuntime(
            self.fabric, self.body, approval_gate=ApprovalGate(store)
        )
        register_mail_runtime(
            runtime,
            config=self.config,
            imap_transport=self.imap,
            credential_store=self.store,
        )
        return runtime, store

    def _send_request(self, event_id: str, **overrides) -> ActionRequest:
        args = {
            "to": ["friend@example.com"],
            "subject": "Plans",
            "body": "See you at noon",
        }
        args.update(overrides)
        return ActionRequest(SEND_ACTION_ID, args, event_id=event_id)

    def test_send_denied_never_reaches_smtp(self):
        runtime, store = self._runtime()
        execution = runtime.execute(self._send_request("evt-send-deny-1"))
        self.assertFalse(execution.success)
        self.assertIn("approval_required", execution.error or "")
        self.assertEqual(self.smtp.calls, [])
        store.decide(store.pending_requests()[0].request_id, "deny")
        retry = runtime.execute(self._send_request("evt-send-deny-2"))
        self.assertFalse(retry.success)
        self.assertIn("approval_required", retry.error or "")
        self.assertEqual(self.smtp.calls, [])

    def test_send_approved_goes_through_and_verifies(self):
        runtime, store = self._runtime()
        first = runtime.execute(self._send_request("evt-send-ok-1"))
        self.assertFalse(first.success)
        self.assertIn("approval_required", first.error or "")
        store.decide(store.pending_requests()[0].request_id, "allow_once")
        second = runtime.execute(self._send_request("evt-send-ok-1"))
        self.assertTrue(second.success, second.error)
        self.assertEqual(len(self.smtp.calls), 1)
        self.assertTrue(second.verification.verified)
        self.assertIn("sent mailbox", second.verification.reason.lower())

    def test_send_replay_refused(self):
        runtime, store = self._runtime()
        runtime.execute(self._send_request("evt-send-replay-1"))
        # always_allow installs an auto-allow rule, so later dispatches
        # pass the gate and reach the replay guard.
        store.decide(store.pending_requests()[0].request_id, "always_allow")
        first = runtime.execute(self._send_request("evt-send-replay-1"))
        self.assertTrue(first.success, first.error)
        # No new approval card is needed: the replay guard refuses the
        # redispatch before the SMTP server is touched again.
        second = runtime.execute(self._send_request("evt-send-replay-1"))
        self.assertFalse(second.success)
        self.assertIn("replay refused", second.error or "")
        self.assertEqual(len(self.smtp.calls), 1)

    def test_send_validates_inputs_after_approval(self):
        runtime, store = self._runtime()
        first = runtime.execute(self._send_request("evt-send-bad-1", subject="  "))
        self.assertFalse(first.success)
        self.assertIn("approval_required", first.error or "")
        store.decide(store.pending_requests()[0].request_id, "allow_once")
        second = runtime.execute(self._send_request("evt-send-bad-1", subject="  "))
        self.assertFalse(second.success)
        self.assertIn("must not be empty", second.error or "")
        self.assertEqual(self.smtp.calls, [])

    def test_read_actions_run_ungated(self):
        runtime, _ = self._runtime()
        execution = runtime.execute(
            ActionRequest(
                LIST_ACTION_ID, {"limit": 5}, event_id="evt-list-1"
            )
        )
        self.assertTrue(execution.success, execution.error)
        report = json.loads(execution.body_result.output)
        self.assertEqual(report["message_count"], 1)
        self.assertEqual(report["messages"][0]["subject"], "Hello")


class MailSkillTests(unittest.TestCase):
    def test_repo_mail_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        mail = [
            item for item in report.tier1 if item.skill_name == "mail"
        ]
        self.assertEqual(len(mail), 1, report.to_dict())
        self.assertTrue(mail[0].passed, mail[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


if __name__ == "__main__":
    unittest.main()
