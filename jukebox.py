import os
import html
import time
import spotipy
import flask
import threading
import logging.config
from werkzeug.serving import make_server
from classic1k import Classic1k, Classic1kError
from spotipy.oauth2 import SpotifyOAuth


class Jukebox:
    DEFAULT_DEVICE_NAME = "Jukebox"

    def __init__(
        self, name, spotify_client, classic1k, shuffle=True, control_playback=False
    ):
        self.name = name
        self.sp = spotify_client

        # card reader for mifare classic1k
        self.classic1k = classic1k
        self.curr_uid = None  # current card ID detected
        self.prev_uid = None  # previous card ID detected

        self.shuffle = shuffle
        self.control_playback = control_playback

        self.log = logging.getLogger(self.__class__.__name__)
        self.log.info("initialized")
        self.log.info("\tshuffle: {}".format(self.shuffle))
        self.log.info("\tcontrol pause/unpause: {}".format(self.control_playback))

    def start_loop(self):
        self.log.info("waiting for playlist card to be presented...")

        while True:
            time.sleep(1)

            card_uid = None
            try:
                card_uid = self.classic1k.check_for_uid(timeout=2)
            except Exception as e:
                self.log.error("inexpected error waiting for card UID: " + str(e))
                continue

            self.curr_uid = card_uid

            if self.curr_uid is None:
                if self.prev_uid is None:
                    self.log.debug("waiting for playlist card to be presented...")
                    continue

                if not self.control_playback:
                    continue

                # if card removed, pause playback
                try:
                    playback_state = self.sp.current_playback()
                    if playback_state["is_playing"]:
                        device_id = self._get_connect_device()["id"]

                        self.log.info("playlist card removed - PAUSE")
                        self.sp.pause_playback(device_id)
                except Exception as e:
                    self.log.error("unexpected error: " + str(e))

            elif self.prev_uid != self.curr_uid:
                self.log.info("new card found")
                try:
                    # try to read playlist uri from detected card
                    playlist_uri = self.classic1k.read_uri(self.curr_uid)
                    self.log.debug("playlist uri: {}".format(playlist_uri))

                    # confirm working playlist in spotify
                    playlist = self.sp.playlist(playlist_uri)
                    self.log.info(
                        "playlist: \n\t{} - {}\n\t{}\n\t{} track(s)".format(
                            playlist["name"],
                            playlist["owner"]["display_name"],
                            html.unescape(playlist["description"]),
                            len(playlist["tracks"]["items"]),
                        )
                    )

                    # get appropriate connect device
                    device = self._get_connect_device()

                    self.log.info("playlist card - PLAY")
                    self.sp.shuffle(self.shuffle, device["id"])
                    self.sp.start_playback(device["id"], context_uri=playlist["uri"])
                    self.log.info("listening on: {}".format(device["name"]))

                    self.prev_uid = self.curr_uid
                except Classic1kError as ce:
                    self.log.error("could not read playlist on card: " + str(ce))
                except Exception as e:
                    self.log.error("unexpected error playing playlist: " + str(e))
            else:
                if not self.control_playback:
                    continue

                # if card was re-inserted, resume playback
                try:
                    playback_state = self.sp.current_playback()
                    if not playback_state["is_playing"]:
                        pos = playback_state["progress_ms"]

                        self.log.info("playlist card - RESUME")
                        self.sp.start_playback(
                            device_id,
                            context_uri=self.curr_playlist_uri,
                            position_ms=pos,
                        )

                        self.curr_uid = self.prev_uid
                except Exception as e:
                    self.log.error("unexpected error: " + str(e))

    def _get_connect_device(self):
        devices = self.sp.devices()["devices"]

        if len(devices) == 0:
            raise ValueError("no available spotify connect devices")

        for device in devices:
            if device["is_active"]:
                return device

            if device["name"] == self.name:
                return device

        self.log.warning("could not active spotify connect device")
        self.log.warning(
            'could not find self "{}" in available connect devices'.format(self.name)
        )
        self.log.warning("falling back to first available connect device")
        return devices[0]


class ServerThread(threading.Thread):
    def __init__(self, app):
        threading.Thread.__init__(self)
        self.server = make_server("0.0.0.0", 8080, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        log.info("starting http server")
        self.server.serve_forever()

    def shutdown(self):
        log.info("stopping http server")
        self.server.shutdown()


if __name__ == "__main__":
    cwd = os.path.dirname(os.path.realpath(__file__))
    logging.config.fileConfig(os.path.join(cwd, "logging.dev.ini"))
    log = logging.getLogger("main")

    # setup reader for mifare classic1k cards
    classic1k = Classic1k()
    
    scope = "user-read-playback-state,user-modify-playback-state,user-read-currently-playing"
    sp_oauth = SpotifyOAuth(scope=scope, open_browser=False)

    http_server = None
    token_info = sp_oauth.get_cached_token()

    if token_info is None:
        # create http server for oauth callback
        app = flask.Flask(__name__)

        @app.route("/callback")
        def callback():
            global token_info
            # TODO: check response for errors?
            code = flask.request.args.get("code")
            token_info = sp_oauth.get_access_token(code)

            return "Logged in!", 200

        # start http server
        http_server = ServerThread(app)
        http_server.start()

        # use mifare card for passing auth url to log into spotify
        log.info("waiting for card to be placed into reader...")
        auth_url = sp_oauth.get_authorize_url()
        log.debug("auth url: " + auth_url)

        while True:
            try:
                uid = classic1k.wait_for_uid()
                # prepare card memory for NDEF message
                classic1k.format(uid)
                # prepare authorize url to card
                classic1k.write_uri(uid, auth_url)
                log.info("present the card to your phone to log into spotify")
                break
            except Classic1kError as ce:
                log.error("failed to write to card: " + str(ce))
            except Exception as e:
                log.error("unexpected error writing spotify oauth url: " + str(e))

            time.sleep(1)

        # wait for user to login to spotify
        while token_info is None:
            time.sleep(1)

    # shutdown http server as it's not required anymore
    if http_server is not None:
        http_server.shutdown()
        del http_server

    spotify_client = spotipy.Spotify(token_info["access_token"])
    device_name = os.getenv("LIBRESPOT_DEVICE_NAME", Jukebox.DEFAULT_DEVICE_NAME)

    # finally, start our jukebox loop
    jb = Jukebox(device_name, spotify_client, classic1k)
    jb.start_loop()
