import json
import logging
import socket
import time

import gi

gi.require_version("Soup", "3.0")

from gi.repository import Gio, GLib, Soup  # type: ignore

log = logging.getLogger(__name__)

from .metric import Gth


def to_graphite(gth: Gth) -> list[dict]:
    return [
        {
            "time": int(time.time()),
            "interval": 60,
            "tags": [f"mac={gth.address}", f"hostname={socket.gethostname()}", f"alias={gth.alias}"],
            **metric,
        }
        for metric in [
            {"name": f"govee.temperature.celsius", "value": gth.temp_celsius},
            {"name": f"govee.humidity.percent", "value": gth.humidity_percent},
            {"name": f"govee.battery.percent", "value": gth.battery_percent},
            {"name": f"govee.rssi", "value": gth.rssi},
        ]
    ]


class Graphite:
    url: str
    user: str | None
    password: str | None
    _session: Soup.Session

    def __init__(self, url: str, user: str | None = None, password: str | None = None):
        self.url = url
        self.user = user
        self.password = password
        self._session = Soup.Session()

        if log.getEffectiveLevel() == logging.DEBUG:
            logger = Soup.Logger.new(Soup.LoggerLogLevel.BODY)
            self._session.add_feature(logger)

    def send_message(self, gth: Gth):
        uri = GLib.Uri.parse(self.url, GLib.UriFlags.NONE)
        message = Soup.Message.new_from_uri("POST", uri)
        if self.user and self.password:
            assert self._session
            auth_manager = self._session.get_feature(Soup.AuthManager)
            assert auth_manager
            auth = Soup.Auth.new(Soup.AuthBasic, message, "Basic")
            assert auth
            auth.authenticate(self.user, self.password)
            auth_manager.use_auth(message.get_uri(), auth)  # type: ignore

        assert message

        body = json.dumps(to_graphite(gth))

        message.set_request_body_from_bytes("application/json", GLib.Bytes.new(body.encode()))

        def response(session: Soup.Session, aresult: Gio.Task):
            bs: GLib.Bytes = session.send_and_read_finish(aresult)
            message = session.get_async_result_message(aresult)
            assert message
            status = message.get_status()
            if status != Soup.Status.OK:
                print(f"Error Posting to '{self.url}': {Soup.Status.get_phrase(status)}")
                return
            if published := json.loads(bs.get_data().decode()).get("published"):  # type: ignore
                print(f"Published {published} Metric")

        self._session.send_and_read_async(message, GLib.PRIORITY_DEFAULT, callback=response)
