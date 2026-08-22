import asyncio
import json
from collections.abc import Awaitable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


async def _send_json_error(send: Send, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestBodyLimitMiddleware:
    """Reject oversized bodies, including streamed/chunked requests."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_body_bytes:
                    await _send_json_error(send, 413, "Request body too large")
                    return
            except ValueError:
                await _send_json_error(send, 400, "Invalid Content-Length header")
                return

        received_bytes = 0
        request_messages: list[Message] = []
        more_body = True

        while more_body:
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    await _send_json_error(send, 413, "Request body too large")
                    return
                more_body = message.get("more_body", False)
            else:
                more_body = False
            request_messages.append(message)

        async def replay_receive() -> Message:
            if request_messages:
                return request_messages.pop(0)
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)


class RequestTimeoutMiddleware:
    """Return 504 when application processing exceeds its deadline."""

    def __init__(self, app: ASGIApp, timeout_seconds: int) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        application_call: Awaitable[None] = self.app(scope, receive, tracked_send)
        try:
            await asyncio.wait_for(
                application_call,
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            if not response_started:
                await _send_json_error(send, 504, "Request processing timed out")
