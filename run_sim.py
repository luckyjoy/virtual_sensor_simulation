import asyncio, argparse, os, sys, yaml, json
from typing import List
import aiomqtt

# On Windows, use SelectorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sensor_sim.sensor import (
    VirtualSensor, SensorIdentity, FaultModel, ValueModel, CSVLogger
)
from sensor_sim.transports import (
    MQTTTransport, MQTTConfig, HTTPTransport, HTTPConfig
)

# ----------------------------
# Safe async CSV writer
# ----------------------------
class QueueCSVLogger:
    def __init__(self, path):
        self.path = path
        self.queue = asyncio.Queue()
        self.file = open(path, "w", newline="", encoding="utf-8")
        self.writer = CSVLogger(path).writer  # reuse CSV writer
        self._task = None

    async def start(self):
        self._task = asyncio.create_task(self._writer())

    async def _writer(self):
        while True:
            payload = await self.queue.get()
            if payload is None:
                break
            try:
                self.writer.writerow(payload)
                self.file.flush()
            except Exception:
                pass
            self.queue.task_done()

    async def log(self, payload):
        await self.queue.put(payload)

    async def stop(self):
        await self.queue.join()
        await self.queue.put(None)
        if self._task:
            await self._task
        self.file.close()


# ----------------------------
# CLI / main
# ----------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Virtual Sensor Simulator")
    p.add_argument("--config", type=str, default="", help="Path to YAML config")
    p.add_argument("--count", type=int, default=100, help="Number of sensors")
    p.add_argument("--rate", type=float, default=1.0, help="Messages per second per sensor")
    p.add_argument("--jitter", type=float, default=0.2, help="Seconds of +/- jitter per publish")
    p.add_argument("--duration", type=int, default=0, help="Seconds to run (0 = infinite)")
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


async def main():
    args = parse_args()
    cfg = {}
    if args.config:
        cfg = load_config(args.config)

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

    # ----------------------------
    # Transport
    # ----------------------------
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

    # ----------------------------
    # Create sensors
    # ----------------------------
    sensors: List[VirtualSensor] = []
    for i in range(count):
        sid = f"vs-{i:04d}"
        ident = SensorIdentity(sensor_id=sid, firmware=firmware, battery_pct=100.0)
        values = ValueModel(base_temp, temp_sd, base_hum, hum_sd)
        faults = FaultModel(drop_rate, spike_rate, fault_every)
        s = VirtualSensor(
            identity=ident, value_model=values, fault_model=faults,
            rate_hz=rate, jitter_s=jitter, battery_drain_pct_per_hour=battery_drain,
            on_publish=None, logger=None  # we handle logging separately
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

            # Assign the safe_publish callback
            for s in sensors:
                s.on_publish = safe_publish

            # Run all sensors
            tasks = [asyncio.create_task(s.run(duration_s=duration)) for s in sensors]
            await asyncio.gather(*tasks)

        print("✅ Simulation completed successfully.", flush=True)
        return 0

    except Exception as e:
        print(f"❌ Unexpected error: {e}", flush=True)
        return 1

    finally:
        print("🧹 Cleaning up...", flush=True)

        # Stop sensors first
        for s in sensors:
            s.stop()

        # Wait for remaining sensor tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Stop logger last
        if logger:
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
