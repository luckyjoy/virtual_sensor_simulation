# sensor_sim/transports.py
import asyncio
from dataclasses import dataclass
import aiomqtt
import aiohttp

# ------------------------------
# MQTT Support
# ------------------------------
@dataclass
class MQTTConfig:
    host: str = "localhost"
    port: int = 1883
    username: str = ""
    password: str = ""
    qos: int = 0
    topic_prefix: str = "sim/sensors"

class MQTTTransport:
    def __init__(self, cfg: MQTTConfig):
        self.cfg = cfg
        self._client: aiomqtt.Client | None = None

    async def __aenter__(self):
        self._client = aiomqtt.Client(
            hostname=self.cfg.host,
            port=self.cfg.port,
            username=self.cfg.username or None,
            password=self.cfg.password or None,
        )
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._client:
            await self._client.__aexit__(exc_type, exc, tb)

    async def publish(self, payload: str):
        if not self._client:
            raise RuntimeError("MQTT client not initialized")
        await self._client.publish(self.cfg.topic_prefix, payload, qos=self.cfg.qos)

# ------------------------------
# HTTP Support
# ------------------------------
@dataclass
class HTTPConfig:
    url: str = "http://localhost:8080/ingest"
    timeout_s: int = 10

class HTTPTransport:
    def __init__(self, cfg: HTTPConfig):
        self.cfg = cfg
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.cfg.timeout_s))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._session:
            await self._session.close()

    async def publish(self, payload: str):
        if not self._session:
            raise RuntimeError("HTTP session not initialized")
        async with self._session.post(self.cfg.url, data=payload) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP publish failed: {resp.status}")
