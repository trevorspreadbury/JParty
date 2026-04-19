"""Bootstrap module."""

import argparse
import logging
import sys
import time
from pathlib import Path

import requests
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication, QMessageBox
from simpleaudio._simpleaudio import SimpleaudioError

from jparty.app.config import DEBUG_MODE, PORT
from jparty.app.paths import SAVED_GAMES
from jparty.domain.game_engine import Game
from jparty.services.archive_client import get_game_html, process_game_board_from_html
from jparty.ui.styles import JPartyStyle
from jparty.ui.widgets.common import resource_path
from jparty.ui.windows.display import DisplayWindow, HostDisplayWindow
from jparty.web.controller import BuzzerController

REQUEST_TIMEOUT_SECONDS = 10
MIN_MONITORS = 2


def check_internet() -> None:
    """Check internet connection"""
    try:
        requests.get("http://www.j-archive.com/", timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.ConnectionError:
        logging.error("Connection Error")
        QMessageBox.critical(
            None,
            "Cannot connect!",
            "JParty cannot connect to the J-Archive. Please check your internet connection.",
            buttons=QMessageBox.StandardButton.Abort,
            defaultButton=QMessageBox.StandardButton.Abort,
        )
        exit(1)


def permission_error() -> None:
    """Run permission error."""
    logging.error(f"Cannot access port {PORT}")
    QMessageBox.critical(
        None,
        "Permission Error",
        f"JParty encountered a permissions error when trying to listen on port {PORT}.",
        buttons=QMessageBox.StandardButton.Abort,
        defaultButton=QMessageBox.StandardButton.Abort,
    )


def audio_error() -> None:
    """Run audio error."""
    logging.error("Cannot access audio device")
    QMessageBox.critical(
        None,
        "Audio error Error",
        "JParty cannot access an audio device.",
        buttons=QMessageBox.StandardButton.Abort,
        defaultButton=QMessageBox.StandardButton.Abort,
    )


def check_second_monitor() -> None:
    """Run check second monitor."""
    if DEBUG_MODE:
        logging.warning("Single monitor mode enabled (DEBUG_MODE)")
        return
    if len(QApplication.instance().screens()) < MIN_MONITORS:
        logging.error("No two monitors")
        QMessageBox.critical(
            None,
            "Two monitors needed!",
            "JParty needs two separate displays. Please attach a second monitor or turn off mirroring and try again.",
            buttons=QMessageBox.StandardButton.Abort,
            defaultButton=QMessageBox.StandardButton.Abort,
        )
        sys.exit(1)


def expand_game_id_inputs(inputs: object) -> object:
    """Run expand game id inputs."""
    game_ids = []
    for raw_input in inputs:
        candidate = Path(raw_input)
        if candidate.exists() and candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                game_id = line.strip()
                if game_id and (not game_id.startswith("#")):
                    game_ids.append(game_id)
        else:
            game_ids.append(raw_input)
    return game_ids


def download_games(inputs: object, delay_seconds: object = 5) -> object:
    """Run download games."""
    downloaded = []
    for game_id in expand_game_id_inputs(inputs):
        print(f"Working on {game_id}")
        saved_path = SAVED_GAMES / f"{game_id}.html"
        if saved_path.exists():
            print("Game already saved")
            continue
        game_html = get_game_html(game_id)
        game_obj = process_game_board_from_html(game_html, game_id)
        if game_obj is None:
            print(f"Skipping {game_id}: downloaded game is invalid or incomplete")
            continue
        with saved_path.open("w", encoding="utf-8") as file_obj:
            file_obj.write(game_html)
        downloaded.append(game_id)
        time.sleep(delay_seconds)
    return downloaded


def build_parser() -> object:
    """Run build parser."""
    parser = argparse.ArgumentParser(prog="jparty")
    subparsers = parser.add_subparsers(dest="command")
    download_parser = subparsers.add_parser(
        "download", help="download archived games into the local saved-games cache"
    )
    download_parser.add_argument(
        "inputs",
        nargs="+",
        help="game ids or text files containing one game id per line",
    )
    return parser


def launch_gui() -> None:
    """Run launch gui."""
    logging.info("Starting JParty")
    QApplication.setStyle(JPartyStyle())
    app = QApplication(sys.argv)
    check_second_monitor()
    check_internet()
    app.setFont(QFont("Verdana"))
    QFontDatabase.addApplicationFont(resource_path("ITC_ Korinna Normal.ttf"))
    game = Game()
    socket_controller = BuzzerController(game)
    game.setBuzzerController(socket_controller)
    try:
        socket_controller.start()
    except PermissionError:
        permission_error()
        exit(1)
    main_window = DisplayWindow(game)
    host_window = HostDisplayWindow(game)
    game.setDisplays(host_window, main_window)
    try:
        game.begin()
    except SimpleaudioError:
        audio_error()
        exit(1)
    song_player = game.song_player
    r = 1
    try:
        r = app.exec()
    finally:
        logging.info("terminated")
        if song_player:
            song_player.stop()
        sys.exit(r)


def main(argv: object = None) -> int | None:
    """Run main."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "download":
        download_games(args.inputs)
        return 0
    launch_gui()
