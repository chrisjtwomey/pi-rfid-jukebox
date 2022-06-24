#!/bin/bash

sudo apt-get update && sudo apt-get -y install python3 python3-pip pulseaudio pulseaudio-module-bluetooth

python3 -m pip install -r requirements.txt
# some weird problem with the board module, quick fix:
python3 -m pip install --force-reinstall adafruit-blinka

sudo cp classic1k.py /usr/local/bin/
sudo cp jukebox.py /usr/local/bin/
sudo cp logging.* /usr/local/bin/
sudo cp scripts/connect-bt.sh /usr/local/bin/
sudo chmod 777 /usr/local/bin/classic1k.py
sudo chmod 777 /usr/local/bin/jukebox.py
sudo chmod 777 /usr/local/bin/logging.*
sudo chmod 777 /usr/local/bin/connect-bt.sh

sudo cp bin/armv6/librespot /usr/bin/
sudo cp scripts/env /etc/pi-rfid-jukebox-env
sudo chmod 777 /usr/bin/librespot /etc/pi-rfid-jukebox-env

sudo systemctl --global disable pulseaudio.service pulseaudio.socket
sudo cp scripts/librespot.service /usr/lib/systemd/user/
sudo cp scripts/pulseaudio.service /usr/lib/systemd/user/
sudo cp scripts/jukebox.service /usr/lib/systemd/user/

source scripts/env

bluetoothctl -- scan on &> /dev/null &
pid=$!

while ! bluetoothctl devices | grep -q $SPEAKER_BT_MAC; do
    echo "scanning for $SPEAKER_BT_MAC..."
    sleep 1
done

bluetoothctl -- pair $SPEAKER_BT_MAC
bluetoothctl -- trust $SPEAKER_BT_MAC

kill $pid

systemctl --user enable --now librespot
systemctl --user enable --now pulseaudio
systemctl --user enable --now jukebox