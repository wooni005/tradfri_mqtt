#!/usr/bin/python3

# Options how to provide Ikea Hub Security Code
# $ ./tradfri_mqtt.py --key <16 char security code>
# $ ./tradfri_mqtt.py -K <16 char security code>
# $ ./tradfri_mqtt.py
# tradfri_mqtt.log: Please provide the 'Security Code' on the back of your Tradfri gateway:
# <16 char security code>


# Hack to allow relative import above top level package
import sys
import os
folder = os.path.dirname(os.path.abspath(__file__))  # noqa
sys.path.insert(0, os.path.normpath("%s/.." % folder))  # noqa

import signal
import _thread
import traceback
from queue import Queue
import paho.mqtt.publish as mqtt_publish
import paho.mqtt.client as mqtt_client

from pytradfri import Gateway
from pytradfri.api.libcoap_api import APIFactory
from pytradfri.error import PytradfriError
from pytradfri.util import load_json, save_json

import uuid
import argparse
import threading
import time
import json

# external files/classes
import logger
import serviceReport
import settings

# Temp-Humi Sensoren THGR810
humStatusTable = ["Dry", "Comfort", "Normal", "Wet"]

# Global vars for the Tradfri Hub API
api     = None
gateway = None
devices = None
lights  = None

observers = {}

lightDevices = {}
lightGroupNames = []

sendQueue = Queue(maxsize=0)
current_sec_time = lambda: int(round(time.time()))
current_milli_time = lambda: int(round(time.time() * 1000))
oldTimeout = 0

exit = False


def signal_handler(_signal, frame):
    global exit

    print('You pressed Ctrl+C!')
    exit = True


def observe(api, device):
    def callback(updated_device):
        light = updated_device.light_control.lights[0]

        maybeGroupName = device.name[0:-2]
        # Check if this light is in a group
        if maybeGroupName in lightGroupNames:
            deviceName = maybeGroupName
        else:
            deviceName = device.name

        #print("Received message for: %s" % light)
        deviceState = {}
        deviceState['state'] = int(light.state)
        deviceState['dimmer'] = light.dimmer
        if light.color_temp is not None:
            # Convert Tradfri color_temp (250-454) to HASS Color range (153-500): HASS_color=(Tradfri_color-250)*(347/204)+153
            data = int((float(light.color_temp) - 250.0) * (347.0 / 204.0) + 153.0)
            deviceState['color_temp'] = data
        #deviceState['supported_features'] = light.supported_features
        #kwhMeterStatus['signal'] = signal
        #kwhMeterStatus['battery'] = battery
        mqtt_publish.single("huis/Tradfri/%s/rx" % deviceName.replace(' ', '-'), json.dumps(deviceState, separators=(', ', ':')), qos=1, hostname=settings.MQTT_ServerIP)

    def err_callback(err):
        print("Observe.err_callback:" + str(err))

    def worker():
        #api(device.observe(callback, err_callback, duration=10)) # duration=10.000 days, no timeout is not possible and default is 60 sec
        api(device.observe(callback, err_callback, duration=864000000)) # duration=10.000 days, no timeout is not possible and default is 60 sec

    maybeGroupName = device.name[0:-2]
    # Check if this light is in a group
    if maybeGroupName in lightGroupNames:
        deviceName = maybeGroupName
    else:
        deviceName = device.name

    # threading.Thread(target=worker, daemon=True).start()
    print(" - Starting observer thread for %s" % deviceName)
    observers[deviceName] = threading.Thread(target=worker, daemon=True)
    observers[deviceName].start()


# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT Client connected successfully")
        client.subscribe([(settings.MQTT_TOPIC_TX, 1),
                          (settings.MQTT_TOPIC_LICHT_AKTIEF, 1),
                          (settings.MQTT_TOPIC_LICHT_HELDERHEID, 1),
                          (settings.MQTT_TOPIC_LICHT_KLEUR, 1),
                          (settings.MQTT_TOPIC_CHECK, 1)])
    else:
        print(("ERROR: MQTT Client connected with result code %s " % str(rc)))


def switchLight(deviceName, state):
    # print('setLight:' + deviceName)

    cmndStr = ("%s;switch;%d" % (deviceName, state))
    sendQueue.put(cmndStr)


def dimLight(deviceName, dimLevel):
    # print('dimLight:' + deviceName)

    cmndStr = ("%s;brightness;%d" % (deviceName, dimLevel))
    sendQueue.put(cmndStr)


def setLightColor(deviceName, color):
    # print('setLightColor:' + deviceName)

    cmndStr = ("%s;color;%d" % (deviceName, color))
    sendQueue.put(cmndStr)


# The callback for when a PUBLISH message is received from the server
def on_message(client, userdata, msg):
    print(('ERROR: Received ' + msg.topic + ' in on_message function' + str(msg.payload)))


def on_message_tx(client, userdata, msg):
    # print(msg.topic + " " + msg.payload.decode())
    topics = msg.topic.split("/")
    # Example topic: huis/Tradfri/Licht TVkamer/out
    deviceName = topics[2].replace('-', ' ')
    action = topics[3] # Like: out, bediening, brightness, color

    if deviceName[0:5] == "Licht":
        if deviceName not in lightDevices:
            print('MQTT_tx: %s-device not found in lightDevices' % deviceName)
        else:
            if action == 'tx':
                msgData = json.loads(msg.payload.decode())
                # print('MQTT_tx: %s-device found in lightDevices and switch light: %d' % (deviceName, msgData['state']))

                if type(msgData) is dict:
                    # Set state
                    if msgData['state'] == 0:
                        # Switch light off, dont't need to set dimming and color
                        switchLight(deviceName, 0)
                    else:
                        # Switch light on
                        switchLight(deviceName, 1)

                        # Set brightness (From 0 to 254)
                        data = msgData['dimmer']
                        if data > 254:
                            data = 254
                        dimLight(deviceName, data)

                        if 'color_temp' in msgData:
                            data = msgData['color_temp']
                            # print('Received HASS color:' + str(data))
                            # Convert color range from HASS color (153-500) to Tradfri color (250-454): Tradfri_color=(HASS_color-153)*(204/347)+250
                            data = int((float(data) - 153.0) * (204.0 / 347.0) + 250.0)
                            # print('Calculated Tradfri color:' + str(data))

                            # Set color: Color value is between 250 and 454
                            if data > 454:
                                data = 454
                            elif data < 250:
                                data = 250
                            setLightColor(deviceName, data)
            else:
                dataStr = msg.payload.decode()

                # Convert data str into int
                if dataStr == '':
                    data = 0
                else:
                    data = int(dataStr)

                if action == 'licht':
                    if data == 1:
                        switchLight(deviceName, 1)
                    else:
                        switchLight(deviceName, 0)
                elif action == 'helderheid':
                    if data > 254:
                        data = 254
                    dimLight(deviceName, data)
                elif action == 'kleur':
                    # Convert color range from HASS color (153-500) to Tradfri color (250-454): Tradfri_color=(HASS_color-153)*(204/347)+250
                    data = int((float(data) - 153.0) * (204.0 / 347.0) + 250.0)

                    # Color value is between 250 and 454
                    if data > 454:
                        data = 454
                    elif data < 250:
                        data = 250
                    setLightColor(deviceName, data)


def sendTradfriCommand(light, command, value):
    if command == 'switch':
        if value == '0':
            # print('switch off:' + light.name)
            off_command = light.light_control.set_state(False)
        else:
            # print('switch on:' + light.name)
            off_command = light.light_control.set_state(True)
        api(off_command)
    elif command == 'brightness':
        dim_command = light.light_control.set_dimmer(int(value))
        api(dim_command)
    elif command == 'color':
        #Color needs to be value between 250 (0x0FA) and 454 (0x1C6)
        #color = 250 #cold (0xf5faf6)
        #color = 374 #normal (0xf1e0b5)
        #color = 454 #warm (efd275)
        color_command = light.light_control.set_color_temp(int(value))
        api(color_command)
    else:
        print('%s: Unknown Tradfri command' % command)


def commandThread():
    global sendQueue

    while True:
        try:
            # Check if there is any message to send via Tradfri gateway
            cmndStr = sendQueue.get()

            if cmndStr != '':
                # print("SendMsg: " + str(cmndStr))
                cmnd = cmndStr.split(';')

                #cmndStr = ("%s;%d;%s;%s" % (unit, state, dimLevel, color))
                # print(cmnd)
                deviceName = cmnd[0]
                command = cmnd[1]
                value = cmnd[2]

                if deviceName in lightDevices:
                    #print("Light: " + deviceName)
                    # If a deviceName contains more lights, send the command
                    # to all lightDevices for this deviceName
                    for singleLight in lightDevices[deviceName]:
                        sendTradfriCommand(singleLight, command, value)
                        # print("   - " + singleLight.name)
            serviceReport.systemWatchTimer = current_sec_time()

        # In case the message contains unusual data
        except ValueError as arg:
            print(arg)
            traceback.print_exc()
            time.sleep(1)

        # Quit the program by Ctrl-C
        except KeyboardInterrupt:
            print("Program aborted by Ctrl-C")
            exit()

        # Handle other exceptions and print the error
        except Exception as arg:
            print("sendTradfriCommand %s" % str(arg))
            time.sleep(1)


def print_time(delay):
    count = 0
    while count < 5:
        time.sleep(delay)
        count += 1
        print("%s" % (time.ctime(time.time())))


def initMQTTinterface():
    # First start the MQTT client
    client = mqtt_client.Client()
    # client.message_callback_add(settings.MQTT_TOPIC_HASS_COMMAND,      on_message_tx)
    # client.message_callback_add(settings.MQTT_TOPIC_HASS_BRIGHTNESS,   on_message_tx)
    # client.message_callback_add(settings.MQTT_TOPIC_HASS_RGB,          on_message_tx)

    client.message_callback_add(settings.MQTT_TOPIC_TX,               on_message_tx)
    client.message_callback_add(settings.MQTT_TOPIC_LICHT_AKTIEF,     on_message_tx)
    client.message_callback_add(settings.MQTT_TOPIC_LICHT_HELDERHEID, on_message_tx)
    client.message_callback_add(settings.MQTT_TOPIC_LICHT_KLEUR,      on_message_tx)
    client.message_callback_add(settings.MQTT_TOPIC_CHECK,            serviceReport.on_message_check)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(settings.MQTT_ServerIP, settings.MQTT_ServerPort, 60)
    client.loop_start()


def initTradfriGatewayAPI():
    global api
    global gateway
    global devices
    global lights
    global lightDevices

    # Get key from commandline when starting for the first time
    parser = argparse.ArgumentParser()
    # parser.add_argument('host', metavar='IP', type=str,
    #                     help='IP Address of your Tradfri gateway')
    parser.add_argument('-K', '--key', dest='key', required=False,
                        help='Security code found on your Tradfri gateway')
    args = parser.parse_args()

    if settings.TRADFRI_HUB_IP not in load_json(settings.CONFIG_FILE) and args.key is None:
        print("Please provide the 'Security Code' on the back of your "
              "Tradfri gateway:", end=" ")
        key = input().strip()
        if len(key) != 16:
            raise PytradfriError("Invalid 'Security Code' provided.")
        else:
            args.key = key

    # Assign configuration variables.
    # The configuration check takes care they are present.
    conf = load_json(settings.CONFIG_FILE)

    try:
        identity = conf[settings.TRADFRI_HUB_IP].get('identity')
        psk = conf[settings.TRADFRI_HUB_IP].get('key')
        api_factory = APIFactory(host=settings.TRADFRI_HUB_IP, psk_id=identity, psk=psk)
    except KeyError:
        identity = uuid.uuid4().hex
        api_factory = APIFactory(host=settings.TRADFRI_HUB_IP, psk_id=identity)

        try:
            psk = api_factory.generate_psk(args.key)
            print('Generated PSK: ', psk)

            conf[settings.TRADFRI_HUB_IP] = {'identity': identity, 'key': psk}
            save_json(settings.CONFIG_FILE, conf)
        except AttributeError:
            raise PytradfriError("Please provide the 'Security Code' on the "
                                 "back of your Tradfri gateway using the "
                                 "-K flag.")

    api = api_factory.request

    gateway = Gateway()

    devices_command = gateway.get_devices()
    devices_commands = api(devices_command)
    devices = api(devices_commands)
    lights = [dev for dev in devices if dev.has_light_control]

    groups_command = gateway.get_groups()
    groups_commands = api(groups_command)
    groups = api(groups_commands)

    # repeaters = [dev for dev in devices if dev.has_signal_repeater_control]
    #
    # print("All repeaters:")
    # print(repeaters)
    # for r in repeaters:
    #     #lightGroupNames.append(r.name)
    #     print("Repeater name:" + r.name)
    #     print(r)

    for g in groups:
        lightGroupNames.append(g.name)
        print("Create light group:" + g.name)

    #print("Found light devices:")
    for light in lights:
        print("- " + light.name + ' id: ' + str(light.id))

        maybeGroupName = light.name[0:-2]
        # Check if this light is in a group
        if maybeGroupName in lightGroupNames:
            # Put this light in a lichtDevice as a group
            if maybeGroupName not in lightDevices:
                print("Make new group: " + maybeGroupName)
                lightDevices[maybeGroupName] = []

            print("Add " + light.name + " to group: " + maybeGroupName)
            lightDevices[maybeGroupName].append(light)
        else:
            print(light.name + " is a separate light")
            lightDevices[light.name] = []
            lightDevices[light.name].append(light)

#
# monitor the device list and give instructions
#

    # groups_command = gateway.get_groups()
    # groups_commands = api(groups_command)
    #
    # groups = api(groups_commands)
    # for g in groups:
    #     groupName = g.name
    #     print("Create light group:" + groupName)
    #     lightGroups[groupName] = []
    #
    #     if groupName in lightDeviceNames[groupName + ' 1']:
    #         # There are more than 1 lights in the group
    #         for id in g.member_ids:
    #             for light in lights:
    #                 if id == light.id:
    #                     lightGroups[groupName].append(light)
    #                     print("- " + light.name + ' id: ' + str(light.id))
    #     else:
    #         # Put only one light device in the groups, the will be controlled separately
    #         pass

    # print(g.name, g.member_ids, g.state, g.dimmer)
    # print("Name:" + str(g.name) + " Status:" + str(g.state) + " Dimmer:" + str(g.dimmer) + " ID: " + str(g.id))

# def jsonify(input):
#     return json.dumps(input, sort_keys=True, indent=4)


###
# Initalisation ####
###
logger.initLogger(settings.LOG_FILENAME)

# Init signal handler, because otherwise Ctrl-C does not work
signal.signal(signal.SIGINT, signal_handler)


# Give Home Assistant and Mosquitto the time to startup
time.sleep(2)

initMQTTinterface()

# Create the commandThread
try:
    # thread.start_new_thread( print_time, (60, ) )
    _thread.start_new_thread(commandThread, ())
except Exception as arg:
    print("%s" % str(arg))
    print("Error: unable to start the commandThread")

initTradfriGatewayAPI()


# Start the observers for all light devices
for deviceName in lightDevices:
    print('Start observer for %s:' % deviceName)
    # If there are more than one lightDevices in a deviceName, monitor only the first one
    light = lightDevices[deviceName][0]
    observe(api, light)
    # print('Sleeping to start observation task')
    time.sleep(1)

while not exit:
    time.sleep(2)  # 60s

    if not exit:
        # Check observers
        for deviceName in observers:
            if not observers[deviceName].is_alive():
                print('Restart observer for %s:' % deviceName)
                serviceReport.sendFailureToHomeLogic(serviceReport.ACTION_NOTHING, 'Observer restarted for: %s' % deviceName)
                # If there are more than one lightDevices in a deviceName, monitor only the first one
                light = lightDevices[deviceName][0]
                observe(api, light)
                # print('Sleeping to start observation task')
                time.sleep(1)

print("Clean exit!")
