import asyncio, argparse, os, sys, yaml, json, csv, time
from typing import List
import aiomqtt

# On Windows, use SelectorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sensor_sim.sensor import (
    VirtualSensor, SensorIdentity, FaultModel, ValueModel
)
from sensor_sim.transports import (
    MQTTTransport, MQTTConfig, HTTPTransport, HTTPConfig
)

# ============================================================
# Reliable async CSV writer with graceful shutdown
# ============================================================
class QueueCSVLogger:
    def __init__(self, path):
        self.path = path
        self.queue = asyncio.Queue()
        self.file = open(path, "w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(
            self.file,
            fieldnames=["sensor_id", "timestamp", "temperature", "humidity", "battery_pct"],
        )
        self.writer.writeheader()
        self._task = None
        self._stopping = False
        self._count = 0

    async def start(self):
        self._task = asyncio.create_task(self._writer_task())

    async def _writer_task(self):
        """Continuously drain the async queue and write to CSV."""
        while True:
            try:
                payload = await asyncio.wait_for(self.queue.get(), timeout=1)
            except asyncio.TimeoutError:
                if self._stopping and self.queue.empty():
                    break
                continue

            if payload is None:
                break

            try:
                if isinstance(payload, dict):
                    self.writer.writerow(payload)
                    self._count += 1
                self.file.flush()
            except Exception as e:
                print(f"⚠️ CSV write error: {e}", flush=True)

            self.queue.task_done()

        print(f"🧾 Logger wrote {self._count} rows to {self.path}", flush=True)

    async def log(self, payload):
        await self.queue.put(payload)

    async def stop(self):
        self._stopping = True
        await self.queue.join()
        await self.queue.put(None)
        if self._task:
            await asyncio.shield(self._task)
        self.file.close()


# ============================================================
# CLI / Config helpers
# ============================================================
def parse_args():
    p = argparse.ArgumentParser(description="Virtual Sensor Simulator")
    p.add_argument("--config", type=str, default="", help="Path to YAML config")
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--rate", type=float, default=1.0)
    p.add_argument("--jitter", type=float, default=0.2)
    p.add_argument("--duration", type=int, default=0)
    p.add_argument("--transport", choices=["mqtt", "http"], default="mqtt")
    # MQTT
    p.add_argument("--mqtt-host", type=str, default="localhost")
    p.add_argument("--mqtt-port", type=int, default=1883)
    p.add_argument("--mqtt-username", type=str, default="")
    p.add_argument("--mqtt-password", type=str, default="")
    p.add_argument("--mqtt-qos", type=int, default=0)
    p.add_argument("--topic-prefix", type=str, default="sim/sensors")
    # HTTP
    p.add_argument("--http-url", type=str, default="http://localhost:8080/ingest")
    p.add_argument("--http-timeout", type=int, default=10)
    # Faults
    p.add_argument("--drop-rate", type=float, default=0.0)
    p.add_argument("--spike-rate", type=float, default=0.0)
    p.add_argument("--fault-every", type=int, default=0)
    # Model
    p.add_argument("--firmware", type=str, default="1.2.3")
    p.add_argument("--battery-drain", type=float, default=0.5)
    p.add_argument("--base-temp", type=float, default=24.0)
    p.add_argument("--temp-sd", type=float, default=0.8)
    p.add_argument("--base-hum", type=float, default=40.0)
    p.add_argument("--hum-sd", type=float, default=3.0)
    p.add_argument("--log-csv", type=str, default="")
    return p.parse_args()


def load_config(path: str):
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


# ============================================================
# Main async entry
# ============================================================
async def main():
    args = parse_args()
    cfg = load_config(args.config) if args.config else {}

    def get_config_value(path: str, default=None):
        cur = cfg
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    count = get_config_value("count", args.count)
    rate = get_config_value("rate", args.rate)
    jitter = get_config_value("jitter", args.jitter)
    duration = get_config_value("duration", args.duration)
    transport = get_config_value("transport", args.transport)

    drop_rate = get_config_value("faults.drop_rate", args.drop_rate)
    spike_rate = get_config_value("faults.spike_rate", args.spike_rate)
    fault_every = get_config_value("faults.fault_every", args.fault_every)

    firmware = get_config_value("sensor.firmware", args.firmware)
    battery_drain = get_config_value("sensor.battery_drain_pct_per_hour", args.battery_drain)
    base_temp = get_config_value("sensor.value.base_temp_c", args.base_temp)
    temp_sd = get_config_value("sensor.value.temp_noise_sd", args.temp_sd)
    base_hum = get_config_value("sensor.value.base_humidity_pct", args.base_hum)
    hum_sd = get_config_value("sensor.value.humidity_noise_sd", args.hum_sd)
    log_csv = get_config_value("log_csv", args.log_csv)

    if transport == "mqtt":
        mqtt_cfg = MQTTConfig(
            host=get_config_value("mqtt.host", args.mqtt_host),
            port=get_config_value("mqtt.port", args.mqtt_port),
            username=get_config_value("mqtt.username", args.mqtt_username),
            password=get_config_value("mqtt.password", args.mqtt_password),
            qos=get_config_value("mqtt.qos", args.mqtt_qos),
            topic_prefix=get_config_value("mqtt.topic_prefix", args.topic_prefix),
        )
        tx_ctx = MQTTTransport(mqtt_cfg)
    else:
        http_cfg = HTTPConfig(
            url=get_config_value("http.url", args.http_url),
            timeout_s=get_config_value("http.timeout_s", args.http_timeout),
        )
        tx_ctx = HTTPTransport(http_cfg)

    logger = QueueCSVLogger(log_csv) if log_csv else None
    if logger:
        await logger.start()

    sensors: List[VirtualSensor] = []
    for i in range(count):
        sid = f"vs-{i:04d}"
        ident = SensorIdentity(sensor_id=sid, firmware=firmware, battery_pct=100.0)
        values = ValueModel(base_temp, temp_sd, base_hum, hum_sd)
        faults = FaultModel(drop_rate, spike_rate, fault_every)
        s = VirtualSensor(
            identity=ident, value_model=values, fault_model=faults,
            rate_hz=rate, jitter_s=jitter, battery_drain_pct_per_hour=battery_drain,
            on_publish=None, logger=None
        )
        sensors.append(s)

    try:
        print(f"🚀 Starting simulation with {count} sensors via {transport.upper()}...", flush=True)
        async with tx_ctx as tx:
            message_counter = 0

            async def safe_publish(payload):
                nonlocal message_counter
                try:
                    await tx.publish(json.dumps(payload))
                    message_counter += 1
                    if message_counter % 100 == 0:
                        print(f"✅ Published {message_counter} messages", flush=True)
                    if logger:
                        await logger.log(payload)
                except Exception as e:
                    print(f"⚠️ Publish error: {e}", flush=True)

            for s in sensors:
                s.on_publish = safe_publish

            tasks = [asyncio.create_task(s.run(duration_s=duration)) for s in sensors]
            await asyncio.gather(*tasks)

        print(f"✅ Simulation completed successfully. Total messages: {message_counter}", flush=True)
        return 0

    except Exception as e:
        print(f"❌ Unexpected error: {e}", flush=True)
        return 1

    finally:
        print("🧹 Cleaning up...", flush=True)
        for s in sensors:
            s.stop()

        if logger:
            print("📦 Flushing CSV logger...", flush=True)
            await logger.stop()

        print("🛑 Simulation stopped gracefully.", flush=True)


if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
    except Exception:
        pass
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n🛑 Keyboard Interrupted. Exiting gracefully...", flush=True)
        sys.exit(0)
