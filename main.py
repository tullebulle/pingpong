#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

import config
from client import run_client_main
from server import run_server_main


def main():
    parser = argparse.ArgumentParser(description="UDP pong game")
    subparsers = parser.add_subparsers(dest="role", required=True)

    srv = subparsers.add_parser("server", help="Run server")
    srv.add_argument("--port", type=int, default=config.SERVER_PORT, help="UDP port to bind")

    cli = subparsers.add_parser("client", help="Run client")
    cli.add_argument("host", type=str, help="Server IP or hostname")
    cli.add_argument("--port", type=int, default=config.SERVER_PORT, help="Server UDP port")

    args = parser.parse_args()

    if args.role == "server":
        run_server_main(port=args.port)
    elif args.role == "client":
        run_client_main(args.host, port=args.port)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main() 