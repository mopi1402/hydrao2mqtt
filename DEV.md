## Developer guide

### Format the code
```bash
cd app && autopep8 --in-place --aggressive --aggressive *.py
```

### Build the Docker image
```bash
docker build -t hydrao2mqtt .
```

### Run the Docker image
```bash
docker run -it --rm -e MQTT_HOST="XXX.XXX.XXX.XXX" -e MQTT_USER="XXX" -e MQTT_PASSWORD="XXX" -e HYDRAO_MAC_ADDRESS="XX:XX:XX:XX:XX:XX" hydrao2mqtt
```
