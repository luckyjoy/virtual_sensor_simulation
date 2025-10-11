# run_sim.py
import asyncio, argparse, random, os, sys, yaml
import json
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

def parse_args():
    p = argparse.ArgumentParser(description="Virtual Sensor Simulator")
    p.add_argument("--config", type=str, default="", help="Path to YAML config")
    p.add_argument("--count", type=int, default=100, help="Number of sensors")
    p.add_argument("--rate", type=float, default=1.0, help="Messages per second per sensor")
    p.add_argument("--jitter", type=float, default=0.2, help="Seconds of +/- jitter per publish")
    p.add_argument("--duration", type=int, default=0, help="Seconds to run (0 = infinite)")
    p.add_argument("--transport", choices=["mqtt","http"], default="mqtt")

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

    # resolve helper to read from cfg or args
    def C(path, default=None):
        cur = cfg
        for part in path.split("."):
            if part in cur:
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

    # Build transport
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

    # CSV logging
    logger = CSVLogger(log_csv) if log_csv else None

    # Create sensors
    sensors: list[VirtualSensor] = []
    for i in range(count):
        sid = f"vs-{i:04d}"
        ident = SensorIdentity(sensor_id=sid, firmware=firmware, battery_pct=100.0)
        values = ValueModel(base_temp, temp_sd, base_hum, hum_sd)
        faults = FaultModel(drop_rate, spike_rate, fault_every)
        # placeholder on_publish; we set after entering transport context
        s = VirtualSensor(
            identity=ident, value_model=values, fault_model=faults,
            rate_hz=rate, jitter_s=jitter, battery_drain_pct_per_hour=battery_drain,
            on_publish=None, logger=logger
        )
        sensors.append(s)

    # Enhanced error handling for the transport
    try:
        print(f"Starting sensor simulation with {count} sensors...")
        async with tx_ctx as tx:
            message_counter = 0

            async def publish(payload):
                nonlocal message_counter
                try:
                    # Convert dictionary to JSON string before publishing
                    json_payload = json.dumps(payload)
                    await tx.publish(json_payload)
                    message_counter += 1
                    # Add a small non-blocking sleep to prevent a message backlog
                    await asyncio.sleep(0.001)
                    if message_counter % 100 == 0:
                        print(f"Successfully published {message_counter} messages.")
                except Exception as e:
                    print(f"Error publishing message: {e}")

            # inject publish callback now that transport is ready
            for s in sensors:
                s.on_publish = publish

            tasks = [asyncio.create_task(s.run(duration_s=duration)) for s in sensors]
            await asyncio.gather(*tasks)

    except aiomqtt.exceptions.MqttError as e:
        print(f"MQTT connection failed: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        print("Simulation stopped.")
        for s in sensors:
            s.stop()

if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
    except Exception:
        pass
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
         print("\n🛑 Keyboard Interrupted. Exiting gracefully...")
        
