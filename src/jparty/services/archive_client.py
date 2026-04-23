"""Load and normalize Jeopardy game data from remote and cached sources.

This module is the service layer responsible for fetching game content from
J-Archive, the Wayback Machine, or Google Sheets exports and transforming those
inputs into the domain models used throughout the application. It also exposes
helpers for locating downloaded clue media and for extracting contestant result
data from archived HTML.
"""

import csv
import json
import logging
import os
import re
from html import unescape

import requests
from bs4 import BeautifulSoup

from jparty.app.config import MONIES
from jparty.app.paths import QUESTION_MEDIA, SAVED_GAMES
from jparty.domain.models import Board, FinalBoard, GameData, Question

REQUEST_TIMEOUT_SECONDS = 10
DOUBLE_JEOPARDY_START_ROW = 14
GOOGLE_SHEETS_ID_LENGTH = 7
_LOADED_GAME_HTML_CACHE = {}


def list_to_game(s: object) -> object:
    """Convert a Google Sheets CSV matrix into a ``GameData`` instance.

    Args:
        s: Two-dimensional sequence of sheet cell values laid out in the
            expected JParty archive format.

    Returns:
        A populated ``GameData`` object containing standard rounds and the
        final round parsed from the sheet data.
    """
    alpha = "BCDEFG"
    boards = []
    for n1 in [1, DOUBLE_JEOPARDY_START_ROW]:
        categories = s[n1 - 1][1:7]
        questions = []
        for row in range(5):
            for col, cat in enumerate(categories):
                address = alpha[col] + str(row + n1 + 1)
                index = (col, row)
                text = s[row + n1][col + 1]
                answer = s[row + n1 + 6][col + 1]
                value = int(s[row + n1][0])
                dd = address in s[n1 - 1][-1]
                questions.append(Question(index, text, answer, cat, value, dd))
        boards.append(Board(categories, questions, dj=n1 == DOUBLE_JEOPARDY_START_ROW))
    fj = s[-1]
    index = (0, 0)
    text = fj[2]
    answer = fj[3]
    category = fj[1]
    question = Question(index, text, answer, category)
    boards.append(FinalBoard(category, question))
    date = fj[5]
    comments = fj[7]
    return GameData(boards, date, comments)


def get_Gsheet_game(file_id: object) -> object:
    """Fetch a Google Sheets game export and parse it into ``GameData``.

    Args:
        file_id: Google Sheets document identifier used to build the CSV export
            URL.

    Returns:
        The parsed ``GameData`` object for the referenced sheet.
    """
    csv_url = f"https://docs.google.com/spreadsheet/ccc?key={file_id}&output=csv"
    with requests.get(csv_url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS) as r:
        lines = (line.decode("utf-8") for line in r.iter_lines())
        r3 = csv.reader(lines)
        return list_to_game(list(r3))


def get_game_html(game_id: object) -> object:
    """Load archived game HTML from disk cache or remote archive sources.

    Args:
        game_id: Numeric J-Archive game identifier used to locate cached or
            remote HTML.

    Returns:
        The raw HTML string for the requested game.
    """
    saved_game_path = SAVED_GAMES / f"{game_id}.html"
    if saved_game_path.exists():
        print("game is saved, try using saved game")
        try:
            with saved_game_path.open("r") as f:
                game_html = f.read()
                _LOADED_GAME_HTML_CACHE[str(game_id)] = game_html
                return game_html
        except UnicodeDecodeError:
            print("UnicodeDecodeError on saved game, trying from internet")
    try:
        print("using wayback machine")
        game_html = get_wayback_game_html(game_id)
    except Exception as e:
        print("using j-archive")
        logging.error(e)
        game_html = get_jarchive_game_html(game_id)
    _LOADED_GAME_HTML_CACHE[str(game_id)] = game_html
    return game_html


def save_game_html(game_id: object) -> object:
    """Persist a played J-Archive game's HTML into the saved-games cache.

    Args:
        game_id: Numeric J-Archive game identifier to save locally.

    Returns:
        The saved HTML path when the game can be cached locally, or ``None``
        for identifiers that are not J-Archive game ids.
    """
    game_id_str = str(game_id)
    if len(game_id_str) >= GOOGLE_SHEETS_ID_LENGTH:
        return None
    saved_game_path = SAVED_GAMES / f"{game_id_str}.html"
    if saved_game_path.exists():
        return saved_game_path
    game_html = _LOADED_GAME_HTML_CACHE.get(game_id_str)
    if game_html is None:
        game_html = get_game_html(game_id_str)
    saved_game_path.write_text(game_html, encoding="utf-8")
    return saved_game_path


def get_game(game_id: object) -> object:
    """Load a game from the appropriate backing source.

    Short numeric identifiers are treated as J-Archive game ids, while longer
    identifiers are treated as Google Sheets ids.

    Args:
        game_id: Game identifier to load from J-Archive-style HTML or a Google
            Sheets export.

    Returns:
        A ``GameData`` instance when the game can be parsed successfully,
        otherwise ``None`` for incomplete or malformed archived games.
    """
    os.environ["JPARTY_GAME_ID"] = str(game_id)
    if len(str(game_id)) < GOOGLE_SHEETS_ID_LENGTH:
        game_html = get_game_html(game_id)
        return process_game_board_from_html(game_html, game_id)
    else:
        return get_Gsheet_game(str(game_id))


def findanswer(clue: object) -> object:
    """Extract the correct response text from a clue HTML fragment.

    Args:
        clue: HTML fragment or object containing the rendered clue markup from
            J-Archive.

    Returns:
        The unescaped correct response text embedded in the clue markup.
    """
    return re.findall('correct_response">(.*?)</em', unescape(str(clue)))[0]


def get_jarchive_game_html(game_id: object) -> object:
    """Fetch raw game HTML directly from J-Archive.

    Args:
        game_id: Numeric J-Archive game identifier.

    Returns:
        The HTML response body returned by J-Archive for the game.
    """
    game_url = f"http://www.j-archive.com/showgame.php?game_id={game_id}"
    r = requests.get(game_url, timeout=REQUEST_TIMEOUT_SECONDS)
    return r.text


def find_question_media(game_id: int, round: int, index: tuple) -> str:
    """Locate downloaded media associated with a clue.

    Args:
        game_id: Numeric game id used to select the media directory.
        round: Zero-based round number for the clue within the archived game.
        index: ``(category, clue)`` tuple identifying the clue position from
            the top-left corner of the board.

    Returns:
        The string path to the matching media file when one exists, otherwise
        ``False``.
    """
    game_media_path = QUESTION_MEDIA / str(game_id)
    if game_media_path.exists():
        potential_filename = f"{round}-{index[0]}-{index[1]}"
        for media_file in game_media_path.iterdir():
            if media_file.stem == potential_filename:
                return str(media_file)
    return False


def get_actual_player_results(clue: BeautifulSoup, value: int) -> object:
    """Extract contestant scoring outcomes for a standard clue.

    Args:
        clue: Parsed clue node from J-Archive containing player result rows.
        value: Dollar value of the clue before any Daily Double override is
            applied.

    Returns:
        A list of ``[player_name, score_delta]`` pairs describing who answered
        correctly or incorrectly.
    """
    dd_value = clue.find(class_="clue_value_daily_double")
    if dd_value is not None:
        value = int(dd_value.text[5:].replace(",", ""))
    wrong_answers = clue.find_all("td", {"class": "wrong"})
    answers = [
        [wrong_answer.text, -value]
        for wrong_answer in wrong_answers
        if wrong_answer.text != "Triple Stumper"
    ]
    right_answer = clue.find("td", {"class": "right"})
    if right_answer:
        answers.append([right_answer.text, value])
    return answers


def get_clue_value(clue: BeautifulSoup, round_index: int, row_index: int) -> int:
    """Extract a clue's dollar value from HTML with a safe fallback.

    Args:
        clue: Parsed clue node from an archived standard round.
        round_index: Zero-based standard-round index in the current game.
        row_index: Zero-based clue row index within the board.

    Returns:
        Parsed dollar value for the clue, or a fallback board value when the
        rendered amount is unavailable.
    """
    value_node = clue.find(class_="clue_value")
    if value_node is not None:
        digits = re.sub(r"[^\d]", "", value_node.text)
        if digits:
            return int(digits)
    fallback_round_index = min(round_index, len(MONIES) - 1)
    return MONIES[fallback_round_index][row_index]


def get_actual_player_final(clue: BeautifulSoup) -> list[list[str]]:
    """Extract contestant scoring outcomes for Final Jeopardy.

    Args:
        clue: Parsed Final Jeopardy clue node containing player wager and
            result rows.

    Returns:
        A list of ``[player_name, score_delta]`` pairs for Final Jeopardy
        outcomes.
    """
    answers = []
    wrong_players = clue.find_all("td", {"class": "wrong"})
    for player_answer in wrong_players:
        value = int(
            player_answer.parent.find_next_sibling("tr")
            .text.strip()[1:]
            .replace(",", "")
        )
        answers.append([player_answer.text, -value])
    right_players = clue.find_all("td", {"class": "right"})
    for player_answer in right_players:
        value = int(
            player_answer.parent.find_next_sibling("tr")
            .text.strip()[1:]
            .replace(",", "")
        )
        answers.append([player_answer.text, value])
    return answers


def process_game_board_from_html(html: object, game_id: object) -> GameData:
    """Parse archived game HTML into domain models.

    Args:
        html: Raw HTML document for a J-Archive game page.
        game_id: Identifier for the game being parsed, used for logging and
            associated media lookups.

    Returns:
        A ``GameData`` object for complete games, or ``None`` when required
        sections are missing or incomplete.
    """
    soup = BeautifulSoup(html, "html.parser")
    title_nodes = soup.select("#game_title > h1")
    comment_nodes = soup.select("#game_comments")
    if not title_nodes or not comment_nodes:
        return None
    datesearch = re.search("- \\w+, (.*?)$", title_nodes[0].text)
    if datesearch is None:
        return None
    date = datesearch.groups()[0]
    comments = comment_nodes[0].contents
    comments = comments[0] if len(comments) > 0 else ""
    boards = []
    rounds = soup.find_all(class_="round")
    for i, ro in enumerate(rounds):
        categories_objs = ro.find_all(class_="category")
        categories = [c.find(class_="category_name").text for c in categories_objs]
        questions = []
        dds = 0
        for clue in ro.find_all(class_="clue"):
            text_obj = clue.find(class_="clue_text")
            if text_obj is None:
                print(f"{game_id} is inccomplete")
                logging.info("this game is incomplete")
                return None
            image_likely = text_obj.find("a")
            image_url = None
            text = text_obj.text
            index_key = text_obj["id"]
            index = (int(index_key[-3]) - 1, int(index_key[-1]) - 1)
            dd = clue.find(class_="clue_value_daily_double") is not None
            if dd:
                dds += 1
            if dds > i + 1:
                dd = False
            value = get_clue_value(clue, i, index[1])
            actual_results = get_actual_player_results(clue, value)
            answer = findanswer(clue)
            potential_media_file = find_question_media(game_id, i, index)
            if potential_media_file:
                image_likely = True
                image_url = potential_media_file
            questions.append(
                Question(
                    index,
                    text,
                    answer,
                    categories[index[0]],
                    value,
                    dd,
                    image=image_likely,
                    image_url=image_url,
                    actual_results=actual_results,
                )
            )
        boards.append(Board(categories, questions, dj=i == 1))
    final_rounds = soup.find_all(class_="final_round")
    if not final_rounds:
        return None
    final_round_obj = final_rounds[0]
    category_obj = final_round_obj.find_all(class_="category")[0]
    category = category_obj.find(class_="category_name").text
    clue = final_round_obj.find_all(class_="clue")[0]
    actual_results = get_actual_player_final(clue)
    text_obj = clue.find(class_="clue_text")
    if text_obj is None:
        logging.info("this game is incomplete")
        return None
    text = text_obj.text
    answer = findanswer(final_round_obj)
    question = Question((0, 0), text, answer, category, actual_results=actual_results)
    boards.append(FinalBoard(category, question))
    return GameData(boards, date, comments)


def get_wayback_game_html(game_id: object) -> object:
    """Fetch the most recent Wayback Machine snapshot for a game page.

    Args:
        game_id: Numeric J-Archive game identifier.

    Returns:
        The archived HTML string from the latest available Wayback snapshot.

    Raises:
        Exception: If no snapshots are available for the requested game.
    """
    JArchive_url = f"j-archive.com/showgame.php?game_id={str(game_id)}"
    url = f"http://web.archive.org/cdx/search/cdx?url={JArchive_url}&collapse=digest&limit=-2&fastLatest=true&output=json"
    urls = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS).text
    parse_url = json.loads(urls)
    if len(parse_url) == 0:
        logging.info("no games found in wayback")
        raise Exception("no games found in wayback")
    url_list = []
    for i in range(1, len(parse_url)):
        orig_url = parse_url[i][2]
        tstamp = parse_url[i][1]
        waylink = tstamp + "/" + orig_url
        final_url = f"http://web.archive.org/web/{waylink}"
        url_list.append(final_url)
    latest_url = url_list[-1]
    r = requests.get(latest_url, timeout=REQUEST_TIMEOUT_SECONDS)
    return r.text


def get_game_sum(soup: object) -> object:
    """Extract summary metadata from a parsed game page.

    Args:
        soup: Parsed BeautifulSoup document for a game page.

    Returns:
        A ``(date, comments)`` tuple containing the broadcast date and game
        comments section content.
    """
    date = re.search(
        "- \\w+, (.*?)$", soup.select("#game_title > h1")[0].contents[0]
    ).groups()[0]
    comments = soup.select("#game_comments")[0].contents
    return (date, comments)


def get_random_game() -> object:
    """Return a random J-Archive game id discovered from the homepage.

    Returns:
        An integer game id scraped from J-Archive's random game link.
    """
    r = requests.get("http://j-archive.com/", timeout=REQUEST_TIMEOUT_SECONDS)
    soup = BeautifulSoup(r.text, "html.parser")
    link = soup.find_all(class_="splash_clue_footer")[1].find("a")["href"]
    return int(link[21:])
