# sensor_sim/sensor.py
import asyncio, random, time, math, json, csv, os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable

ISO = "%Y-%m-%dT%H:%M:%S.%fZ"

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime(ISO)

@dataclass
class FaultModel:
    drop_rate: float = 0.0       # skip sending
    spike_rate: float = 0.0      # send anomalous value
    fault_every: int = 0         # force every N messages
    _counter: int = field(default=0, init=False)

    def should_drop(self) -> bool:
        self._counter += 1
        if self.fault_every and self._counter % self.fault_every == 0:
            return True
        return random.random() < self.drop_rate

    def should_spike(self) -> bool:
        return random.random() < self.spike_rate

@dataclass
class ValueModel:
    base_temp_c: float = 24.0
    temp_noise_sd: float = 0.8
    base_humidity_pct: float = 40.0
    humidity_noise_sd: float = 3.0

    def reading(self, spike: bool=False) -> Dict[str, float]:
        temp = random.gauss(self.base_temp_c, self.temp_noise_sd)
        hum  = random.gauss(self.base_humidity_pct, self.humidity_noise_sd)
        if spike:
            # Introduce abnormal spikes or out-of-range values
            temp *= random.choice([0.5, 1.8, -1.0])
            hum  *= random.choice([0.2, 2.5, -0.5])
        return {"temperature_c": round(temp, 2), "humidity_pct": round(hum, 2)}

@dataclass
class SensorIdentity:
    sensor_id: str
    firmware: str = "1.0.0"
    battery_pct: float = 100.0

@dataclass
class CSVLogger:
    path: Optional[str] = None
    _writer: Optional[csv.DictWriter] = field(default=None, init=False)
    _fh: Any = field(default=None, init=False)
    _created: bool = field(default=False, init=False)

    def write(self, row: Dict[str, Any]):
        if not self.path: 
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not self._created:
            self._fh = open(self.path, "w", newline="")
            self._writer = csv.DictWriter(self._fh, fieldnames=list(row.keys()))
            self._writer.writeheader()
            self._created = True
        self._writer.writerow(row)
        self._fh.flush()

    def close(self):
        try:
            if self._fh: self._fh.close()
        except Exception:
            pass

class VirtualSensor:
    def __init__(
        self,
        identity: SensorIdentity,
        value_model: ValueModel,
        fault_model: FaultModel,
        rate_hz: float = 1.0,
        jitter_s: float = 0.0,
        battery_drain_pct_per_hour: float = 0.5,
        on_publish: Optional[Callable[[Dict[str, Any]], asyncio.Future]] = None,
        logger: Optional[CSVLogger] = None,
    ):
        self.identity = identity
        self.value_model = value_model
        self.fault_model = fault_model
        self.period = 1.0 / max(rate_hz, 0.001)
        self.jitter_s = jitter_s
        self.battery_drain = battery_drain_pct_per_hour
        self.on_publish = on_publish
        self.logger = logger
        self.seq = 0
        self._stop = asyncio.Event()

    def stop(self):
        self._stop.set()

    async def run(self, duration_s: int = 0):
        start = time.time()
        while not self._stop.is_set():
            if duration_s and (time.time() - start) >= duration_s:
                break
            # Timing with jitter
            sleep_for = self.period + random.uniform(-self.jitter_s, self.jitter_s)
            await asyncio.sleep(max(0.0, sleep_for))
            # Battery drain
            self.identity.battery_pct = max(0.0, self.identity.battery_pct - (self.battery_drain / 3600.0) * self.period)
            # Fault injection
            if self.fault_model.should_drop():
                continue
            spike = self.fault_model.should_spike()
            values = self.value_model.reading(spike=spike)
            self.seq += 1
            payload = {
                "sensor_id": self.identity.sensor_id,
                "ts": utc_now_iso(),
                "battery_pct": round(self.identity.battery_pct, 2),
                **values,
                "firmware": self.identity.firmware,
                "status": "OK" if not spike else "WARN",
                "seq": self.seq,
            }
            if self.on_publish:
                await self.on_publish(payload)
            if self.logger:
                self.logger.write(payload)
        if self.logger:
            self.logger.close()
