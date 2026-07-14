from __future__ import annotations

from email.message import EmailMessage

from corvid.domain.compose import DraftMessage
from corvid.service.send import SendService


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


class FakeRecorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.recorded: list[EmailMessage] = []
        self._fail = fail

    def record_sent(self, message: EmailMessage) -> None:
        if self._fail:
            raise RuntimeError("APPEND failed")
        self.recorded.append(message)


def _draft() -> DraftMessage:
    return DraftMessage(from_addr="me@x", to=["you@y"], subject="Hi", body_text="hello")


def test_send_delivers_and_records() -> None:
    sender, recorder = FakeSender(), FakeRecorder()
    message = SendService(sender, recorder).send(_draft())
    assert sender.sent == [message]
    assert recorder.recorded == [message]
    assert message["Subject"] == "Hi"


def test_send_without_recorder() -> None:
    sender = FakeSender()
    SendService(sender).send(_draft())
    assert len(sender.sent) == 1


def test_recorder_failure_is_swallowed() -> None:
    sender, recorder = FakeSender(), FakeRecorder(fail=True)
    # Send succeeded even though recording to Sent failed.
    message = SendService(sender, recorder).send(_draft())
    assert sender.sent == [message]
    assert recorder.recorded == []
