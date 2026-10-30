"""Parsers that normalize external game sources into domain models."""

from __future__ import annotations

import csv
import logging
import re
from html import unescape

from bs4 import BeautifulSoup

from jparty.app.config import MONIES
from jparty.app.paths import QUESTION_MEDIA
from jparty.domain.models import Board, FinalBoard, GameData, Question
from jparty.services import question_media as question_media_service

DOUBLE_JEOPARDY_START_ROW = 14


class GameParser:
    """Parse CSV and HTML source payloads into ``GameData``."""

    def normalize_comments(self, comment_node: object) -> str:
        """Return plain-text comments extracted from one HTML node."""
        if comment_node is None:
            return ""
        if hasattr(comment_node, "get_text"):
            return str(comment_node.get_text(" ", strip=True))
        return str(comment_node).strip()

    def list_to_game(self, rows: list[list[str]]) -> GameData:
        """Convert a Google Sheets CSV matrix into ``GameData``."""
        alpha = "BCDEFG"
        boards = []
        for start_row in [1, DOUBLE_JEOPARDY_START_ROW]:
            categories = rows[start_row - 1][1:7]
            questions = []
            for row in range(5):
                for col, category in enumerate(categories):
                    address = alpha[col] + str(row + start_row + 1)
                    index = (col, row)
                    text = rows[row + start_row][col + 1]
                    answer = rows[row + start_row + 6][col + 1]
                    value = int(rows[row + start_row][0])
                    dd = address in rows[start_row - 1][-1]
                    questions.append(Question(index, text, answer, category, value, dd))
            boards.append(
                Board(categories, questions, dj=start_row == DOUBLE_JEOPARDY_START_ROW)
            )
        final_row = rows[-1]
        question = Question((0, 0), final_row[2], final_row[3], final_row[1])
        boards.append(FinalBoard(final_row[1], question))
        return GameData(boards, final_row[5], final_row[7])

    def csv_text_to_game(self, csv_text: str) -> GameData:
        """Convert raw CSV export text into ``GameData``."""
        return self.list_to_game(list(csv.reader(csv_text.splitlines())))

    def findanswer(self, clue: object) -> str:
        """Extract the correct response text from a clue HTML fragment."""
        return re.findall('correct_response">(.*?)</em', unescape(str(clue)))[0]

    def find_question_media(self, game_id: int, round_index: int, index: tuple) -> str:
        """Locate downloaded media associated with a clue."""
        question_media_service.QUESTION_MEDIA = QUESTION_MEDIA
        return question_media_service.find_question_media_file(
            game_id, round_index, index
        )

    def get_actual_player_results(self, clue: BeautifulSoup, value: int) -> list[list]:
        """Extract contestant scoring outcomes for a standard clue."""
        daily_double_value = clue.find(class_="clue_value_daily_double")
        if daily_double_value is not None:
            value = int(daily_double_value.text[5:].replace(",", ""))
        answers = [
            [wrong_answer.text, -value]
            for wrong_answer in clue.find_all("td", {"class": "wrong"})
            if wrong_answer.text != "Triple Stumper"
        ]
        right_answer = clue.find("td", {"class": "right"})
        if right_answer:
            answers.append([right_answer.text, value])
        return answers

    def get_clue_value(
        self, clue: BeautifulSoup, round_index: int, row_index: int
    ) -> int:
        """Extract a clue's dollar value from HTML with a safe fallback."""
        value_node = clue.find(class_="clue_value")
        if value_node is not None:
            digits = re.sub(r"[^\d]", "", value_node.text)
            if digits:
                return int(digits)
        fallback_round_index = min(round_index, len(MONIES) - 1)
        return MONIES[fallback_round_index][row_index]

    def get_actual_player_final(self, clue: BeautifulSoup) -> list[list[str]]:
        """Extract contestant scoring outcomes for Final Jeopardy."""
        answers = []
        for player_answer in clue.find_all("td", {"class": "wrong"}):
            value = int(
                player_answer.parent.find_next_sibling("tr")
                .text.strip()[1:]
                .replace(",", "")
            )
            answers.append([player_answer.text, -value])
        for player_answer in clue.find_all("td", {"class": "right"}):
            value = int(
                player_answer.parent.find_next_sibling("tr")
                .text.strip()[1:]
                .replace(",", "")
            )
            answers.append([player_answer.text, value])
        return answers

    def process_game_board_from_html(
        self, html: object, game_id: object
    ) -> GameData | None:
        """Parse archived game HTML into domain models."""
        soup = BeautifulSoup(html, "html.parser")
        title_nodes = soup.select("#game_title > h1")
        comment_nodes = soup.select("#game_comments")
        if not title_nodes or not comment_nodes:
            return None
        date_search = re.search(r"- .*?, (.*?)$", title_nodes[0].text)
        if date_search is None:
            return None
        date = date_search.groups()[0]
        comments = self.normalize_comments(comment_nodes[0])

        boards = []
        rounds = soup.find_all(class_="round")
        for round_index, round_node in enumerate(rounds):
            categories = [
                category.find(class_="category_name").text
                for category in round_node.find_all(class_="category")
            ]
            questions = []
            daily_double_count = 0
            for clue in round_node.find_all(class_="clue"):
                text_obj = clue.find(class_="clue_text")
                if text_obj is None:
                    logging.warning(
                        "Skipping missing clue in game %s round %s",
                        game_id,
                        round_index,
                    )
                    continue
                image_likely = bool(text_obj.find("a"))
                image_url = None
                index_key = text_obj["id"]
                index = (int(index_key[-3]) - 1, int(index_key[-1]) - 1)
                daily_double = clue.find(class_="clue_value_daily_double") is not None
                if daily_double:
                    daily_double_count += 1
                if daily_double_count > round_index + 1:
                    daily_double = False
                value = self.get_clue_value(clue, round_index, index[1])
                potential_media_file = self.find_question_media(
                    game_id, round_index, index
                )
                if potential_media_file:
                    image_likely = True
                    image_url = potential_media_file
                questions.append(
                    Question(
                        index,
                        text_obj.text,
                        self.findanswer(clue),
                        categories[index[0]],
                        value,
                        daily_double,
                        image=image_likely,
                        image_url=image_url,
                        actual_results=self.get_actual_player_results(clue, value),
                    )
                )
            boards.append(Board(categories, questions, dj=round_index == 1))

        final_rounds = soup.find_all(class_="final_round")
        if not final_rounds:
            return None
        final_round = final_rounds[0]
        category = (
            final_round.find_all(class_="category")[0].find(class_="category_name").text
        )
        clue = final_round.find_all(class_="clue")[0]
        text_obj = clue.find(class_="clue_text")
        if text_obj is None:
            logging.info("Game %s is incomplete", game_id)
            return None
        question = Question(
            (0, 0),
            text_obj.text,
            self.findanswer(final_round),
            category,
            actual_results=self.get_actual_player_final(clue),
        )
        boards.append(FinalBoard(category, question))
        return GameData(boards, date, comments)

    def get_game_sum(self, soup: object) -> tuple[str, object]:
        """Extract summary metadata from a parsed game page."""
        date = re.search(
            r"- .*?, (.*?)$", soup.select("#game_title > h1")[0].contents[0]
        ).groups()[0]
        comments = self.normalize_comments(soup.select("#game_comments")[0])
        return (date, comments)
