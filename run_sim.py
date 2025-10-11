import asyncio, argparse, random, os, sys, yaml, json
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
# Async-safe CSV Logger
# ----------------------------
class SafeCSVLogger(CSVLogger):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._closed = False
        self._lock = asyncio.Lock()

    async def log_async(self, record):
        async with self._lock:
            if self._closed:
                return
            try:
                self.writer.writerow(record)
                self.file.flush()
            except Exception:
                pass

    def log(self, record):
        try:
            asyncio.run(self.log_async(record))
        except Exception:
            pass

    def close(self):
        self._closed = True
        try:
            super().close()
        except Exception:
            pass

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
        """Retrieve a nested value from the config dictionary using dot-separated keys."""
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

    # Transport
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

    logger = SafeCSVLogger(log_csv) if log_csv else None

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
            on_publish=None, logger=logger
        )

        # Wrap run() to prevent publishing after stop
        s._stopping = False
        old_run = s.run

        async def safe_run(duration_s=0, sensor=s):
            start = asyncio.get_event_loop().time()
            while True:
                now = asyncio.get_event_loop().time()
                if duration_s and now - start >= duration_s:
                    break
                payload = sensor.generate_payload()
                if sensor.on_publish and not getattr(sensor, "_stopping", False):
                    try:
                        await sensor.on_publish(payload)
                    except Exception:
                        pass
                await asyncio.sleep(sensor.next_interval())

        s.run = safe_run

        # Wrap stop() to set _stopping
        old_stop = s.stop
        def safe_stop(sensor=s):
            sensor._stopping = True
            old_stop()
        s.stop = safe_stop

        sensors.append(s)

    # ----------------------------
    # Run simulation
    # ----------------------------
    try:
        print(f"🚀 Starting simulation with {count} sensors via {transport.upper()}...", flush=True)
        async with tx_ctx as tx:
            message_counter = 0

            async def publish(payload):
                nonlocal message_counter
                try:
                    await tx.publish(json.dumps(payload))
                    message_counter += 1
                    if message_counter % 100 == 0:
                        print(f"✅ Published {message_counter} messages", flush=True)
                    await asyncio.sleep(0.001)
                except Exception as e:
                    print(f"⚠️ Publish error: {e}", flush=True)

            for s in sensors:
                async def safe_publish(payload, pub=publish):
                    try:
                        await pub(payload)
                    except Exception:
                        pass
                s.on_publish = safe_publish

            tasks = [asyncio.create_task(s.run(duration_s=duration)) for s in sensors]
            await asyncio.gather(*tasks)

        print("✅ Simulation completed successfully.", flush=True)
        return 0

    except aiomqtt.exceptions.MqttError as e:
        print(f"❌ MQTT connection failed: {e}", flush=True)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", flush=True)
        return 1

    finally:
        print("🧹 Cleaning up...", flush=True)

        # Stop sensors
        for s in sensors:
            s.stop()

        # Cancel and await all tasks
        all_tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in all_tasks:
            t.cancel()
        await asyncio.gather(*all_tasks, return_exceptions=True)

        # Close transport/session safely
        for s in sensors:
            session = getattr(s, "session", None)
            if session and hasattr(session, "close") and not session.closed:
                try:
                    await session.close()
                except Exception:
                    pass

        # Close logger last
        if logger:
            try:
                logger.close()
            except Exception:
                pass

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
