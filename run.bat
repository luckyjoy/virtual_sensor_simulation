@echo off
REM Create the virtual environment if it doesn't exist
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)
start "Start Mosquitto Subscriber: mosquitto_sub -h localhost -t sim/sensors/#" mosquitto_sub -h localhost -t sim/sensors/#
REM Run the Python script directly using the venv's interpreter
start /wait "Python Simulator with 100 sensors in .venv" .venv\Scripts\python run_sim.py --count 100 --transport mqtt --mqtt-host localhost --mqtt-port 1883 --topic-prefix sim/sensors --rate 1.0 && pause
