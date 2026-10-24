import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect

from app.core.config import Settings

logger = logging.getLogger(__name__)


class AriRequestError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class AriClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._http = httpx.AsyncClient(
            base_url=f"{settings.asterisk_ari_url.rstrip('/')}/",
            auth=(
                settings.asterisk_ari_username,
                settings.asterisk_ari_password.get_secret_value(),
            ),
            timeout=httpx.Timeout(5.0),
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        missing_ok: bool = False,
    ) -> Any:
        response = await self._http.request(
            method,
            path.lstrip("/"),
            params=params,
            json=json_body,
        )
        if missing_ok and response.status_code == 404:
            return None
        if response.is_error:
            raise AriRequestError(
                response.status_code,
                f"ARI request failed ({method} {path}): HTTP {response.status_code}",
            )
        if not response.content:
            return None
        return response.json()

    async def create_bridge(self, bridge_id: str) -> None:
        await self.request(
            "POST",
            f"/bridges/{bridge_id}",
            params={"type": "mixing,proxy_media", "name": bridge_id},
        )

    async def add_channels(self, bridge_id: str, channel_ids: list[str]) -> None:
        await self.request(
            "POST",
            f"/bridges/{bridge_id}/addChannel",
            params={"channel": ",".join(channel_ids)},
        )

    async def answer(self, channel_id: str) -> None:
        await self.request("POST", f"/channels/{channel_id}/answer")

    async def create_media_channel(
        self,
        *,
        session_id: str,
        channel_id: str,
    ) -> None:
        await self.request(
            "POST",
            "/channels/externalMedia",
            params={
                "app": self._settings.asterisk_ari_app,
                "channelId": channel_id,
                "external_host": self._settings.asterisk_media_websocket_client,
                "transport": "websocket",
                "encapsulation": "none",
                "connection_type": "client",
                "format": self._settings.asterisk_media_format,
                "direction": "both",
                "transport_data": f"f(json)v(session_id={session_id})",
            },
        )

    async def hangup(self, channel_id: str) -> None:
        await self.request("DELETE", f"/channels/{channel_id}", missing_ok=True)

    async def destroy_bridge(self, bridge_id: str) -> None:
        await self.request("DELETE", f"/bridges/{bridge_id}", missing_ok=True)

    async def list_channels(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/channels")

    async def event_stream(self, stop: asyncio.Event) -> AsyncIterator[dict[str, Any]]:
        parts = urlsplit(self._settings.asterisk_ari_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        query = urlencode(
            {"app": self._settings.asterisk_ari_app}
        )
        uri = urlunsplit(
            (scheme, parts.netloc, f"{parts.path.rstrip('/')}/events", query, "")
        )
        credentials = (
            f"{self._settings.asterisk_ari_username}:"
            f"{self._settings.asterisk_ari_password.get_secret_value()}"
        ).encode()
        authorization = base64.b64encode(credentials).decode("ascii")
        async with connect(
            uri,
            open_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            additional_headers={"Authorization": f"Basic {authorization}"},
        ) as websocket:
            yield {"type": "AriConnected"}
            while not stop.is_set():
                try:
                    payload = await asyncio.wait_for(websocket.recv(), timeout=1)
                except TimeoutError:
                    continue
                if isinstance(payload, str):
                    event = json.loads(payload)
                    if isinstance(event, dict):
                        yield event


class AriEventLoop:
    def __init__(
        self,
        client: AriClient,
        session_manager: Any,
        ai_extension: str,
    ):
        self._client = client
        self._sessions = session_manager
        self._ai_extension = ai_extension
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.is_connected = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="asterisk-ari-events")

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        retry_seconds = 1
        while not self._stop.is_set():
            try:
                async for event in self._client.event_stream(self._stop):
                    if event.get("type") == "AriConnected":
                        self.is_connected = True
                        retry_seconds = 1
                        await self._reconcile()
                    else:
                        await self._dispatch(event)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("ARI event connection interrupted: %s", type(error).__name__)
            finally:
                self.is_connected = False

            if not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=retry_seconds)
                except TimeoutError:
                    retry_seconds = min(retry_seconds * 2, 15)

    async def _dispatch(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        channel = event.get("channel") or {}
        channel_id = channel.get("id")
        if not channel_id:
            return

        if event_type == "StasisStart":
            if self._sessions.get_by_media_channel(channel_id):
                return
            dialplan = channel.get("dialplan") or {}
            if dialplan.get("exten") == self._ai_extension:
                await self._sessions.start_call(channel_id)
        elif event_type in {"StasisEnd", "ChannelDestroyed"}:
            session = self._sessions.get_by_caller_channel(channel_id)
            if session:
                await self._sessions.end_call(session, hangup_caller=False)

    async def _reconcile(self) -> None:
        try:
            channels = await self._client.list_channels()
        except Exception as error:
            logger.warning("ARI channel reconciliation failed: %s", type(error).__name__)
            return
        active_channel_ids = {channel.get("id") for channel in channels}
        for session in self._sessions.all_sessions():
            if session.caller_channel_id not in active_channel_ids:
                await self._sessions.end_call(session, hangup_caller=False)
