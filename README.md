# tradfri_mqtt

 Communication service between the Ikea Tradfri gateway and MQTT

## Installing the python3 modules

```bash
$ 
```

## Installeren pytradfri

Source: https://github.com/ggravlingen/pytradfri

```bash
$ sudo pip3 install pytradfri
of update
$ sudo pip3 install --upgrade pytradfri
```

### Building and installing  libcoap

```bash
$ sudo apt install git autoconf automake libtool
```

```bash
$ cd
$ mkdir coap
$ cd coap
$ vi install-coap-client.sh

#!/bin/sh
git clone --depth 1 --recursive -b dtls https://github.com/home-assistant/libcoap.git
cd libcoap
./autogen.sh
./configure --disable-documentation --disable-shared --without-debug CFLAGS="-D COAP_DEBUG_FD=stderr"
make
make install

$ sudo chmod +x install-coap-client.sh
$ sudo ./install-coap-client.sh
```
