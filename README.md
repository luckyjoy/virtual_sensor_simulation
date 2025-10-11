# Virtual Sensor Simulator (100+ sensors)
# MQTT (Message Queuing Telemetry Transport) is a lightweight, publish-subscribe messaging protocol. 
# It's used in environments with low bandwidth or unreliable network connections, such as IoT devices.
# The protocol operates on a client-server model with a central component called a broker.
# Publisher: A client that sends messages to the broker.
# Subscriber: A client that receives messages from the broker.
# Broker: The server that receives all messages from publishers, filters them by topic, and distributes them to all interested subscribers.


# start mosquitto
# netstat -an | findstr 1883
mqtt broker: mosquitto_sub -h localhost -t "sim/sensors/#"

The Virtual sensor simulator's functionality and performance Designed for **embedded/firmware CI/CD** load and integration testing. 
Uses asyncio for scale, with configurable rates, jitter, payload schemas, and fault injection. 
The primary goals are to:
- Test functionality: Verify that the script can create 100 virtual sensors and that the MQTTTransport successfully connects to a local MQTT broker.
- Test data and transport: Confirm that sensor data is generated, serialized to JSON, and correctly published over MQTT.
- Test load: Evaluate the system's ability to handle a total message rate of 100 messages per second without errors.
- Test configuration: Ensure that command-line arguments are correctly parsed and applied to the simulation settings.

## Quick Start

### 1) Create and activate a venv (optional)
```bash
python3 -m venv .venv && source .venv/bin/activate  # on Windows: python -m venv .venv && .venv\Scripts\activate
```

### 2) Install requirements
```bash
pip install -r requirements.txt
```

### 3) Run 100 sensors over MQTT
```bash
python run_sim.py --count 100 --transport mqtt --mqtt-host localhost --mqtt-port 1883 --topic-prefix sim/sensors --rate 1.0
```

### 4) Or run over HTTP (POST to a collector endpoint)
```bash
python run_sim.py --count 100 --transport http --http-url http://localhost:8080/ingest --rate 1.0
```

### 5) Use a config file instead of long CLI args
```bash
python run_sim.py --config sensor_sim/config.yaml
```

### 6) With Docker + Mosquitto broker
```bash
docker compose up --build
# In another shell (or override), run the simulator container with your args
docker compose run --rm simulator python run_sim.py --count 100 --transport mqtt --mqtt-host mosquitto --topic-prefix sim/sensors
```

## Features
- Async **100–10,000** virtual sensors (limited by your host/network)
- **MQTT** (QoS 0/1) via `asyncio-mqtt` or **HTTP** via `aiohttp`
- Configurable **rate**, **jitter**, **duration**, **payload schema**, **fault injection**
- **Per-sensor identity**, location, battery model, and sensor value noise
- **CSV logging** of published payloads (optional)
- **Graceful shutdown** & backpressure handling
- Works locally or in CI (GitHub Actions example included)

## Example payload
```json
{
  "sensor_id": "vs-0042",
  "ts": "2025-08-28T21:00:00.123Z",
  "battery_pct": 92.3,
  "temperature_c": 24.8,
  "humidity_pct": 41.2,
  "firmware": "1.2.3",
  "status": "OK",
  "seq": 512
}
```

## CI usage (smoke)
Limit to 20 sensors @ 1 Hz for 60 s:
```bash
python run_sim.py --count 20 --duration 60 --rate 1 --transport mqtt --mqtt-host $BROKER_HOST
```

## Tips
- Start small (20 sensors) then scale up.
- Use `--drop-rate` for network loss, `--spike-rate` for bad readings, and `--fault-every` for deterministic faults.
- If you run many sensors, prefer a single process with asyncio (as this project does) instead of 100 OS processes.
