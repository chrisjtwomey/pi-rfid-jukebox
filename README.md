# RFID BT Raspberry Pi Jukebox

Jukebox that uses a PN532 reader and Mifare Classic1k RFID cards to control spotify playback.

This is for a project that is enclosed in a DIY bluetooth speaker system with [Librespot](https://github.com/librespot-org/librespot) as Spotify Connect client and Pulseaudio as bt-audio backend.

## Hardware requirements

- Raspberry Pi (any board with SDA, SCL pins)
- PN532 with i2c (eg. [Elechouse PN532](https://www.elechouse.com/product/pn532-nfc-rfid-module-v4/))
- [Mifare Classic 1K cards](https://shop.pimoroni.com/products/rfid-card-10-pcs)


## Usage

```
git clone https://github.com/chrisjtwomey/pi-rfid-jukebox.git
cd pi-rfid-jukebox
pip3 install -r requirements.txt

echo "export SPOTIPY_CLIENT_ID=<XXXX>" >> .env
echo "export "SPOTIPY_CLIENT_SECRET=<XXXX>" >> .env
echo "export "SPOTIPY_REDIRECT_URI=http://<your hostname>:8080/callback" >> .env
source .env

python3 jukebox.py
```

Place RFID cards with Spotify playlist URIs embedded within to have Spotify play that playlist.