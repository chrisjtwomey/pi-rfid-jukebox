#!/bin/bash

systemctl --user disable --now jukebox
systemctl --user disable --now librespot
systemctl --user disable --now pulseaudio

sudo rm -rf /usr/lib/systemd/user/jukebox.service
sudo rm -rf /usr/lib/systemd/user/librespot.service
sudo rm -rf /usr/lib/systemd/user/pulseaudio.service

sudo systemctl --global enable pulseaudio.service pulseaudio.socket

sudo rm /usr/bin/librespot
sudo rm /etc/pi-rfid-jukebox-env
sudo rm /usr/local/bin/jukebox.py /usr/local/bin/classic1k.py /usr/local/bin/logging.* /usr/local/bin/connect-bt.sh
