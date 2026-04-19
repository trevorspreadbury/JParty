"""Archive client module."""

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
STANDARD_AND_FINAL_ROUND_COUNT = 3


def list_to_game(s: object) -> object:
    """Run list to game."""
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
    """Run get gsheet game."""
    csv_url = f"https://docs.google.com/spreadsheet/ccc?key={file_id}&output=csv"
    with requests.get(csv_url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS) as r:
        lines = (line.decode("utf-8") for line in r.iter_lines())
        r3 = csv.reader(lines)
        return list_to_game(list(r3))


def get_game_html(game_id: object) -> object:
    """Run get game html."""
    saved_game_path = SAVED_GAMES / f"{game_id}.html"
    if saved_game_path.exists():
        print("game is saved, try using saved game")
        try:
            with saved_game_path.open("r") as f:
                game_html = f.read()
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
    return game_html


def get_game(game_id: object) -> object:
    """Run get game."""
    os.environ["JPARTY_GAME_ID"] = str(game_id)
    if len(str(game_id)) < GOOGLE_SHEETS_ID_LENGTH:
        game_html = get_game_html(game_id)
        return process_game_board_from_html(game_html, game_id)
    else:
        return get_Gsheet_game(str(game_id))


def findanswer(clue: object) -> object:
    """Run findanswer."""
    return re.findall('correct_response">(.*?)</em', unescape(str(clue)))[0]


def get_jarchive_game_html(game_id: object) -> object:
    """Run get jarchive game html."""
    game_url = f"http://www.j-archive.com/showgame.php?game_id={game_id}"
    r = requests.get(game_url, timeout=REQUEST_TIMEOUT_SECONDS)
    return r.text


def find_question_media(game_id: int, round: int, index: tuple) -> str:
    """Return path to question media or False if none exist

    Args:
        game_id: game id
        round: round number, 1-jeopardy, 2-double jeopardy
        index: (category, question) index, from top left 0-indexed
    """
    game_media_path = QUESTION_MEDIA / str(game_id)
    if game_media_path.exists():
        potential_filename = f"{round}-{index[0]}-{index[1]}"
        for media_file in game_media_path.iterdir():
            if media_file.stem == potential_filename:
                return str(media_file)
    return False


def get_actual_player_results(clue: BeautifulSoup, value: int) -> object:
    """Get the results from the actual jeopardy contestants"""
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


def get_actual_player_final(clue: BeautifulSoup) -> list[list[str]]:
    """Run get actual player final."""
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
    """Given j-archive html, produce a game data object"""
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
    if len(rounds) == STANDARD_AND_FINAL_ROUND_COUNT:
        rounds = rounds[:2]
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
            value = MONIES[i][index[1]]
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
    """Run get wayback game html."""
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
    """Run get game sum."""
    date = re.search(
        "- \\w+, (.*?)$", soup.select("#game_title > h1")[0].contents[0]
    ).groups()[0]
    comments = soup.select("#game_comments")[0].contents
    return (date, comments)


def get_random_game() -> object:
    """Use j-archive's random game feature to get a random game id"""
    r = requests.get("http://j-archive.com/", timeout=REQUEST_TIMEOUT_SECONDS)
    soup = BeautifulSoup(r.text, "html.parser")
    link = soup.find_all(class_="splash_clue_footer")[1].find("a")["href"]
    return int(link[21:])
