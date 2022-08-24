MQTT_ServerIP = "192.168.5.248"
MQTT_ServerPort = 1883
# DHCP client list name: GW-XXXXXXXXXXXX
TRADFRI_HUB_IP = '192.168.5.129'
LOG_FILENAME = "/home/pi/log/tradfri_mqtt.log"
CONFIG_FILE = 'tradfri_standalone_psk.conf'

MQTT_TOPIC_TX = "huis/Tradfri/+/tx"
MQTT_TOPIC_RX = "huis/Tradfri/+/rx"
MQTT_TOPIC_CHECK = "huis/Tradfri/RPiHome/check"
MQTT_TOPIC_REPORT = "huis/Tradfri/RPiHome/report"

# Following topics are working but not used, /tx is used
MQTT_TOPIC_LICHT_AKTIEF = "huis/Tradfri/+/licht"
MQTT_TOPIC_LICHT_HELDERHEID = "huis/Tradfri/+/helderheid"
MQTT_TOPIC_LICHT_KLEUR = "huis/Tradfri/+/kleur"
