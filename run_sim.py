import asyncio, argparse, random, os, sys, yaml, json
from typing import List
import aiomqtt

# On Windows, use the SelectorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sensor_sim.sensor import (
    VirtualSensor, SensorIdentity, FaultModel, ValueModel, CSVLogger
)
from sensor_sim.transports import (
    MQTTTransport, MQTTConfig, HTTPTransport, HTTPConfig
)

# 🩵 Patch CSVLogger to ignore writes after close
class SafeCSVLogger(CSVLogger):
    def log(self, record):
        try:
            super().log(record)
        except (ValueError, RuntimeError):
            # File closed or invalid state, safe to ignore
            pass

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

    def C(path, default=None):
        cur = cfg
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    count = C("count", args.count)
    rate = C("rate", args.rate)
    jitter = C("jitter", args.jitter)
    duration = C("duration", args.duration)
    transport = C("transport", args.transport)

    drop_rate = C("faults.drop_rate", args.drop_rate)
    spike_rate = C("faults.spike_rate", args.spike_rate)
    fault_every = C("faults.fault_every", args.fault_every)

    firmware = C("sensor.firmware", args.firmware)
    battery_drain = C("sensor.battery_drain_pct_per_hour", args.battery_drain)
    base_temp = C("sensor.value.base_temp_c", args.base_temp)
    temp_sd = C("sensor.value.temp_noise_sd", args.temp_sd)
    base_hum = C("sensor.value.base_humidity_pct", args.base_hum)
    hum_sd = C("sensor.value.humidity_noise_sd", args.hum_sd)
    log_csv = C("log_csv", args.log_csv)

    if transport == "mqtt":
        mqtt_cfg = MQTTConfig(
            host=C("mqtt.host", args.mqtt_host),
            port=C("mqtt.port", args.mqtt_port),
            username=C("mqtt.username", args.mqtt_username),
            password=C("mqtt.password", args.mqtt_password),
            qos=C("mqtt.qos", args.mqtt_qos),
            topic_prefix=C("mqtt.topic_prefix", args.topic_prefix),
        )
        tx_ctx = MQTTTransport(mqtt_cfg)
    else:
        http_cfg = HTTPConfig(
            url=C("http.url", args.http_url),
            timeout_s=C("http.timeout_s", args.http_timeout),
        )
        tx_ctx = HTTPTransport(http_cfg)

    # Use SafeCSVLogger instead of plain CSVLogger
    logger = SafeCSVLogger(log_csv) if log_csv else None

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
        sensors.append(s)

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

            # Start all sensors
            tasks = [asyncio.create_task(s.run(duration_s=duration)) for s in sensors]

            # Wait for all tasks to complete
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

        # Stop all sensors
        for s in sensors:
            s.stop()

        # Wait for all remaining tasks to finish safely
        all_tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in all_tasks:
            t.cancel()
        await asyncio.gather(*all_tasks, return_exceptions=True)

        # Close transport/session
        for s in sensors:
            session = getattr(s, "session", None)
            if session and hasattr(session, "close") and not session.closed:
                try:
                    await session.close()
                except Exception:
                    pass

        # Close CSV logger last
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
