import argparse
import logging
import os
import socket
import sys
import time
from dataclasses import dataclass

from .graphite import Graphite
from .prometheus import PushGateway

log = logging.getLogger(__name__)
import json

import gi

gi.require_version("Gio", "2.0")
from gi.repository import GLib  # type: ignore

from gth_exporter.bluez import GthScanner
from gth_exporter.metric import Gth

log = logging.getLogger(__name__)


LOGLEVELS = {
    "DEBUG": logging.debug,
    "INFO": logging.info,
    "WARNING": logging.warning,
    "ERROR": logging.error,
    "CRITICAL": logging.critical,
}


def setup_logging(args):
    logging.basicConfig(
        level=args.log_level,
        format=("%(levelname)-8s %(message)s" if os.environ.get("JOURNAL_STREAM") else "%(asctime)s %(levelname)-8s %(message)s"),
    )


def main():
    parser = argparse.ArgumentParser(
        prog="GoveeLife Bluetooth Thermometer Hygrometer Exporter",
        description="Export metrics. Use environment variables METRICS_USER and METRICS_PASSWORD for authentication",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-l",
        "--log-level",
        choices=LOGLEVELS.keys(),
        help="log level",
        default="WARNING",
    )
    parser.add_argument(
        "-a",
        "--alias",
        default=[],
        type=str,
        action="append",
        help="Set aliases for specified device (e.g.: C4:7C:8D:XX:YY:ZZ=Bromeliad). Can be repeated",
    )
    parser.add_argument("-t", "--timeout", type=int, default=60, help="Scan timeout")
    parser.add_argument("-b", "--bluetooth-adapter", type=str, default="hci0", help="Bluetooth Adapter to use")
    parser.add_argument("-g", "--graphite-url", type=str, required=False, help="Post Metrics to Graphite Metrics URL")
    parser.add_argument("-p", "--prometheus-url", type=str, required=False, help="Post Metrics to Prometheus Pushgateway URL")
    args = parser.parse_args(sys.argv[1:])
    setup_logging(args)
    alias_mapping = dict([alias_s.split("=") for alias_s in args.alias])
    mainloop = GLib.MainLoop()
    # Graphite Support
    if args.graphite_url:
        graphite = Graphite(args.graphite_url, os.getenv("METRICS_USER"), os.getenv("METRICS_PASSWORD"))
    else:
        graphite = None
    # Prometheus Pushgateway support
    if args.prometheus_url:
        prometheus = PushGateway(args.prometheus_url, os.getenv("METRICS_USER"), os.getenv("METRICS_PASSWORD"))
    else:
        prometheus = None

    def metrics_callback(gth: Gth):
        if graphite:
            graphite.send_message(gth)
        if prometheus:
            prometheus.send_message(gth)
        print(gth)

    gth_scanner = GthScanner(alias_mapping, metrics_callback)
    gth_scanner.setup_adapter(args.bluetooth_adapter)

    def stop():
        log.debug("Stopping discovery")
        gth_scanner.stop_discovery(mainloop.quit)

    GLib.timeout_add_seconds(args.timeout, stop)
    mainloop.run()


if __name__ == "__main__":
    main()
