#!/bin/bash

SPEAKER_BT_MAC=$1

bluetoothctl -- scan on &> /dev/null &
pid=$!

while ! bluetoothctl devices | grep -q $SPEAKER_BT_MAC; do
    echo "scanning for $SPEAKER_BT_MAC..."
    sleep 1
done

bluetoothctl -- pair $SPEAKER_BT_MAC
bluetoothctl -- trust $SPEAKER_BT_MAC
bluetoothctl -- connect $SPEAKER_BT_MAC

kill $pid