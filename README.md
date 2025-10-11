# 🚀 Virtual Sensor Simulator (100+ Sensors)

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg?logo=python)](https://www.python.org/)  
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)  
[![Build](https://img.shields.io/github/actions/workflow/status/luckyjoy/virtual_sensor_simulation/ci.yml?label=CI%2FCD)](https://github.com/luckyjoy/virtual_sensor_simulation/actions)  
[![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)](https://hub.docker.com/)  
[![MQTT](https://img.shields.io/badge/MQTT-Asyncio--MQTT-orange)](https://mqtt.org/)

A high-performance **virtual IoT sensor simulator** built for **embedded systems** and **firmware CI/CD** environments.  
It enables **large‑scale load testing**, **data validation**, and **MQTT / HTTP transport** performance benchmarking.

---

## 📘 Overview

The simulator uses **Python asyncio** to achieve high concurrency, while allowing full configuration of:

- Message rate, jitter, and duration  
- Sensor payload schemas and noise  
- Fault injection and recovery  
- Logging and telemetry analysis  

### 🎯 Primary Goals

- Validate sensor message generation and JSON serialization  
- Benchmark MQTT and HTTP transports  
- Assess system throughput (e.g. 100+ msgs/sec)  
- Provide consistent configuration via CLI or YAML  

---

### ⚙️ Installation

```bash
git clone git clone https://github.com/luckyjoy/virtual_sensor_simulation.git
cd robotics_tdd
pip install -r requirements.txt  # Optional for local testing
```

---

## 🌐 MQTT Architecture

**MQTT (Message Queuing Telemetry Transport)** is a lightweight pub/sub protocol suited for IoT or constrained / lossy networks.

| Role        | Description                                 |
|-------------|---------------------------------------------|
| **Publisher**  | Sends sensor data messages to the broker     |
| **Subscriber** | Receives messages from broker subscriptions |
| **Broker**     | Routes messages between publishers & subscribers |

---

## 🗺️ MQTT Flow Diagram

```mermaid
graph TD
    A[Virtual Sensors] -->|Publish JSON data| B[MQTT Broker (Mosquitto)]
    B -->|Route by topic: sim/sensors/#| C[Subscribers / Consumers]
    C -->|Store / Analyze / Visualize| D[Data Platform or Dashboard]
```

---

## 📁 Project Structure

```
virtual_sensor_simulation/
├── .github/
│   └── workflows/
│       └── ci.yml
├── sensor_sim/
│   ├── __init__.py
│   ├── config.yaml
│   ├── simulator.py
│   └── … (other modules, classes, utils, etc.)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── run_sim.py
├── .dockerignore
├── .gitignore
└── README.md
```

---

## ⚙️ Features

- 🧩 Async simulation supporting **100–10,000 sensors** (host / network dependent)  
- 🌐 Two transport modes: *MQTT* (QoS 0 / 1 via `asyncio-mqtt`) or *HTTP* (POST via `aiohttp`)  
- ⚡ Fully configurable: message rate, jitter, duration, schemas, and fault injection  
- 🧪 Per-sensor identity: battery models, location, noise profiles  
- 📊 Optional CSV logging of all emitted messages  
- 🧘 Graceful shutdown & built-in backpressure handling  
- 🧱 CI‑friendly: designed to run in GitHub Actions, Jenkins, or other pipelines  

---

## 🚀 Quick Start

### 1. Create & activate a Python virtual environment

```bash
python3 -m venv .venv && source .venv/bin/activate
# On Windows:
python -m venv .venv && .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run 100 sensors over MQTT

```bash
python run_sim.py --count 100 --transport mqtt   --mqtt-host localhost --mqtt-port 1883   --topic-prefix sim/sensors --rate 1.0
```

### 4. Run over HTTP

```bash
python run_sim.py --count 100 --transport http   --http-url http://localhost:8080/ingest --rate 1.0
```

### 5. Use a config file

```bash
python run_sim.py --config sensor_sim/config.yaml
```

### 6. Using Docker + Mosquitto

```bash
docker compose up --build
# In another terminal:
docker compose run --rm simulator python run_sim.py   --count 100 --transport mqtt --mqtt-host mosquitto --topic-prefix sim/sensors
```

---

## 🧪 Example Payload

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

---

## 🧱 CI/CD Smoke Test Example

Launch 20 sensors at 1 Hz for 60 seconds:

```bash
python run_sim.py --count 20 --duration 60 --rate 1   --transport mqtt --mqtt-host $BROKER_HOST
```

---

## 🧠 Tips & Best Practices

- Start small (e.g. 20 sensors) before scaling up.  
- Use flags like `--drop-rate`, `--spike-rate`, `--fault-every` to simulate edge conditions.  
- Prefer asyncio concurrency over multiple processes for efficiency.  
- Monitor CPU, memory, and network utilization at scale.  

---

## 🧩 License & Contributions

This project is licensed under the **MIT License**.  
Contributions, issues, and pull requests are welcome — feel free to open discussions or propose enhancements.

---

© 2025 Virtual Sensor Simulator | Maintained by [luckyjoy](https://github.com/luckyjoy)
