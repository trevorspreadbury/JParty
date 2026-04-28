"""Application startup helpers and command-line entry points.

This module prepares the JParty runtime, including network and display checks,
GUI startup, and the small command-line workflow used to download archived
games into the local cache. It serves as the main bridge between the packaged
application entry point and the rest of the runtime services.
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import requests
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication, QMessageBox
from simpleaudio._simpleaudio import SimpleaudioError

from jparty.app.config import DEBUG_MODE, PORT
from jparty.app.paths import SAVED_GAMES
from jparty.domain.game_engine import Game
from jparty.domain.state import build_end_game_summary, reconstruct_score_history
from jparty.services.archive_client import get_game_html, process_game_board_from_html
from jparty.ui.styles import JPartyStyle
from jparty.ui.widgets.common import resource_path
from jparty.ui.widgets.final import EndGameSummaryDisplay
from jparty.ui.windows.display import DisplayWindow, HostDisplayWindow
from jparty.web.controller import BuzzerController

REQUEST_TIMEOUT_SECONDS = 10
MIN_MONITORS = 2
SUMMARY_IMAGE_NAME = "summary.png"
SUMMARY_IMAGE_SIZE = (1920, 1080)
DEFAULT_UI_FONT_FAMILIES = ("Verdana", "Arial", "Sans Serif")
EMOJI_FALLBACK_FONT_FAMILIES = (
    "Segoe UI Emoji",
    "Apple Color Emoji",
    "Noto Color Emoji",
    "Segoe UI Symbol",
    "Noto Emoji",
)


def should_force_offscreen_platform(env: object = None) -> bool:
    """Return whether summary rendering should force Qt's offscreen platform."""
    current_env = env or os.environ
    if current_env.get("QT_QPA_PLATFORM"):
        return False
    if os.name == "nt" or sys.platform == "darwin":
        return False
    return not (current_env.get("DISPLAY") or current_env.get("WAYLAND_DISPLAY"))


def ui_font_families(available_families: object) -> list[str]:
    """Return the preferred UI font stack with emoji-capable fallbacks."""
    available = set(available_families)
    families = [
        family for family in DEFAULT_UI_FONT_FAMILIES if family in available
    ] or [DEFAULT_UI_FONT_FAMILIES[0]]
    families.extend(
        family
        for family in EMOJI_FALLBACK_FONT_FAMILIES
        if family in available and family not in families
    )
    return families


def build_ui_font(font_database: object = None) -> QFont:
    """Build the application font with OS emoji fallbacks when available."""
    available_families = (
        font_database.families()
        if font_database is not None
        else QFontDatabase.families()
    )
    families = ui_font_families(available_families)
    font = QFont(families[0])
    if hasattr(font, "setFamilies"):
        font.setFamilies(families)
    return font


def configure_application_font(app: QApplication) -> None:
    """Apply the shared UI font stack used across runtime entry points."""
    app.setFont(build_ui_font())


def check_internet() -> None:
    """Verify that J-Archive is reachable before starting the app.

    Returns:
        ``None``.

    Raises:
        SystemExit: Exits the process after showing an error dialog when the
            J-Archive host cannot be reached.
    """
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
    """Show an error dialog for a socket binding permission failure.

    Returns:
        ``None``.
    """
    logging.error(f"Cannot access port {PORT}")
    QMessageBox.critical(
        None,
        "Permission Error",
        f"JParty encountered a permissions error when trying to listen on port {PORT}.",
        buttons=QMessageBox.StandardButton.Abort,
        defaultButton=QMessageBox.StandardButton.Abort,
    )


def audio_error() -> None:
    """Show an error dialog for audio device initialization failures.

    Returns:
        ``None``.
    """
    logging.error("Cannot access audio device")
    QMessageBox.critical(
        None,
        "Audio error Error",
        "JParty cannot access an audio device.",
        buttons=QMessageBox.StandardButton.Abort,
        defaultButton=QMessageBox.StandardButton.Abort,
    )


def check_second_monitor() -> None:
    """Ensure the application has access to two displays when required.

    Returns:
        ``None``.

    Raises:
        SystemExit: Exits the process after showing an error dialog when fewer
            than two screens are available outside debug mode.
    """
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
    """Expand CLI download inputs into a flat list of game ids.

    Each input can be either a direct game id or a text file containing one id
    per line. Blank lines and comment lines beginning with ``#`` are ignored.

    Args:
        inputs: Iterable of raw command-line input strings supplied to the
            download command.

    Returns:
        A list of game id strings collected from the provided inputs.
    """
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
    """Download and cache archived game HTML for the requested ids.

    Args:
        inputs: Iterable of game ids or text-file paths containing game ids.
        delay_seconds: Delay inserted between successful downloads to avoid
            hammering remote archive services.

    Returns:
        A list of game ids that were downloaded and written to the local cache.
    """
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
    """Construct the command-line parser for the JParty entry point.

    Returns:
        An ``argparse.ArgumentParser`` configured with the supported subcommands
        and arguments.
    """
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
    summary_parser = subparsers.add_parser(
        "summary",
        help="render an end-of-game summary image from a saved game-state directory",
    )
    summary_parser.add_argument(
        "--game-state-directory",
        required=True,
        help="path to a saved game-state directory containing general.json",
    )
    summary_parser.add_argument(
        "--output-file",
        help="output image path (defaults to <game-state-directory>/summary.png)",
    )
    return parser


def summary_output_path(
    game_state_directory: object, output_file: object = None
) -> Path:
    """Resolve the image path for a rendered summary command.

    Args:
        game_state_directory: Base saved game-state directory.
        output_file: Optional explicit output path from the CLI.

    Returns:
        Path to the summary image that should be written.
    """
    game_state_path = Path(game_state_directory)
    if output_file:
        return Path(output_file)
    return game_state_path / SUMMARY_IMAGE_NAME


def load_summary_from_game_state_directory(game_state_directory: object) -> object:
    """Build an end-game summary payload from a saved game-state directory.

    Args:
        game_state_directory: Directory containing ``general.json`` and
            ``question_history.jsonl``.

    Returns:
        An ``EndGameSummary`` payload matching the in-app audience summary.

    Raises:
        FileNotFoundError: If the required metadata file is missing.
        ValueError: If the game state metadata cannot be used to build a
            playable summary.
    """
    from jparty.services.game_loader import (
        build_game_from_board_selection_configs,
        get_game,
    )

    game_state_path = Path(game_state_directory)
    general_file = game_state_path / "general.json"
    if not general_file.exists():
        raise FileNotFoundError("Saved game folder must contain general.json")
    with general_file.open(encoding="utf-8") as file_obj:
        general_state = json.load(file_obj)

    game_id = str(general_state.get("game_id", "")).strip()
    if not game_id:
        raise ValueError("Saved game metadata is missing a game_id")

    board_selection_configs = general_state.get("board_selections")
    if board_selection_configs:
        data = build_game_from_board_selection_configs(board_selection_configs)
    else:
        data = get_game(game_id)
        if data is None:
            raise ValueError("Saved game points to an invalid or incomplete game")
        selected_round_indices = general_state.get("selected_round_indices")
        if selected_round_indices is not None:
            data.rounds = [
                data.rounds[int(index)]
                for index in selected_round_indices
                if 0 <= int(index) < len(data.rounds)
            ]
    if data is None:
        raise ValueError("Saved game points to an invalid or incomplete game")

    summary_game = SimpleNamespace(
        _game_state_dir=game_state_path,
        data=data,
        players=[],
    )
    score_history = reconstruct_score_history(summary_game)
    players = []
    for saved_player in general_state.get("players", []):
        player_number = int(saved_player.get("player_number", 0))
        players.append(
            SimpleNamespace(
                player_number=player_number,
                name=str(saved_player.get("name", f"Player {player_number}")),
                score=score_history.get(player_number, [0])[-1],
            )
        )
    summary_game.players = players
    return build_end_game_summary(summary_game)


def render_summary_image(summary: object, output_file: object) -> Path:
    """Render an end-game summary payload to an image file.

    Args:
        summary: ``EndGameSummary`` payload to render.
        output_file: Destination image path.

    Returns:
        The written output path.

    Raises:
        ValueError: If the widget cannot be saved to the requested output path.
    """
    if should_force_offscreen_platform():
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        QApplication.setStyle(JPartyStyle())
        configure_application_font(app)
        QFontDatabase.addApplicationFont(resource_path("ITC_ Korinna Normal.ttf"))
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    widget = EndGameSummaryDisplay(summary)
    widget.resize(*SUMMARY_IMAGE_SIZE)
    widget.show()
    app.processEvents()
    pixmap = widget.grab()
    widget.close()
    if not pixmap.save(str(output_path)):
        raise ValueError(f"Could not save summary image to {output_path}")
    return output_path


def generate_summary_image(
    game_state_directory: object, output_file: object = None
) -> Path:
    """Generate an end-game summary image from a saved game-state directory.

    Args:
        game_state_directory: Directory containing persisted game state.
        output_file: Optional destination path for the rendered image.

    Returns:
        The output path that was written.
    """
    summary = load_summary_from_game_state_directory(game_state_directory)
    resolved_output = summary_output_path(game_state_directory, output_file)
    return render_summary_image(summary, resolved_output)


def launch_gui() -> None:
    """Start the full JParty desktop application.

    This initializes the Qt application, validates runtime requirements, wires
    together the game engine and buzzer controller, and enters the main event
    loop.

    Returns:
        ``None``.
    """
    logging.info("Starting JParty")
    QApplication.setStyle(JPartyStyle())
    app = QApplication(sys.argv)
    check_second_monitor()
    check_internet()
    configure_application_font(app)
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
    """Run the JParty command-line entry point.

    Args:
        argv: Optional iterable of argument strings to parse instead of using
            ``sys.argv``.

    Returns:
        ``0`` when a CLI subcommand completes successfully, otherwise the GUI
        launch path does not return a status code before handing control to Qt.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "download":
        download_games(args.inputs)
        return 0
    if args.command == "summary":
        output_path = generate_summary_image(
            args.game_state_directory, args.output_file
        )
        print(f"Wrote summary image to {output_path}")
        return 0
    launch_gui()
