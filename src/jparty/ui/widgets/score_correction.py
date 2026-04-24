"""Host-side widgets for editing recent score history."""

from base64 import urlsafe_b64decode

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

RESULT_OPTIONS = ("no answer", "correct", "incorrect")
SIGNATURE_PREFIX = "data:image/png;base64"
PLAYER_NAME_IMAGE_HEIGHT = 40
PLAYER_NAME_IMAGE_WIDTH = 120
RADIO_BUTTON_STYLE = """
QRadioButton {
    color: white;
    font-weight: 700;
    background-color: #18354a;
    border: 1px solid #6db3e4;
    border-radius: 8px;
    padding: 6px 12px;
}
QRadioButton::indicator {
    width: 18px;
    height: 18px;
}
QRadioButton::indicator:unchecked {
    border: 2px solid #f3c969;
    background: #09131d;
    border-radius: 9px;
}
QRadioButton::indicator:checked {
    border: 2px solid #f3c969;
    background: #f3c969;
    border-radius: 9px;
}
"""


class ScoreCorrectionDialog(QDialog):
    """Modal host dialog for editing recent clue rulings."""

    def __init__(
        self, entries: list[dict], players: list[object], parent: object = None
    ) -> None:
        """Initialize the score-correction dialog.

        Args:
            entries: Recent clue-entry view models from the game engine.
            players: Active players available for score correction.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.entries = entries
        self.players = players
        self._entry_widgets = []
        self.setWindowTitle("Edit Score")
        self.resize(900, 640)

        layout = QVBoxLayout()
        intro = QLabel(
            "Review the five most recent clues and update any player ruling."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        content_layout = QVBoxLayout()
        for entry in entries:
            content_layout.addWidget(self._build_entry_group(entry))
        content_layout.addStretch()
        content.setLayout(content_layout)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def _create_player_identity_widget(self, player: object, parent: object) -> object:
        """Create a label widget for a player's typed name or signature image.

        Args:
            player: Player shown in the correction dialog.
            parent: Parent widget.

        Returns:
            Configured ``QLabel`` for the player's identity.
        """
        player_label = QLabel(parent)
        player_label.setMinimumWidth(PLAYER_NAME_IMAGE_WIDTH)
        player_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        if str(player.name).startswith(SIGNATURE_PREFIX):
            image = QImage()
            image.loadFromData(urlsafe_b64decode(str(player.name)[22:]), "PNG")
            pixmap = QPixmap.fromImage(image)
            if not pixmap.isNull():
                player_label.setPixmap(
                    pixmap.scaledToHeight(
                        PLAYER_NAME_IMAGE_HEIGHT,
                        mode=Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return player_label
        player_label.setText(f"{player.name}:")
        player_label.setStyleSheet("color: white; font-weight: 700;")
        return player_label

    def _build_entry_group(self, entry: dict) -> object:
        """Create one clue editor section.

        Args:
            entry: Clue-entry view model from the game engine.

        Returns:
            Configured ``QGroupBox``.
        """
        title = f"Q{entry['question_number']}: {entry['category']}"
        group = QGroupBox(title, self)
        group_layout = QVBoxLayout()

        summary_layout = QHBoxLayout()
        summary_layout.addWidget(QLabel(f"Value: {entry['value']}", group))
        if entry["is_daily_double"]:
            value_input = QSpinBox(group)
            value_input.setRange(5, 50000)
            value_input.setValue(int(entry["value"]))
            summary_layout.addWidget(QLabel("Daily Double value:", group))
            summary_layout.addWidget(value_input)
        else:
            value_input = None
        summary_layout.addStretch()
        group_layout.addLayout(summary_layout)

        answer_label = QLabel(f"Answer: {entry['answer']}", group)
        answer_label.setWordWrap(True)
        answer_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        group_layout.addWidget(answer_label)

        player_rows_layout = QVBoxLayout()
        player_controls = {}
        for player in self.players:
            row_layout = QHBoxLayout()
            player_label = self._create_player_identity_widget(player, group)
            row_layout.addWidget(player_label)

            button_group = QButtonGroup(group)
            radio_buttons = {}
            current_value = entry["player_states"].get(
                player.player_number, "no answer"
            )
            for option in RESULT_OPTIONS:
                radio = QRadioButton(option.title(), group)
                radio.setChecked(option == current_value)
                radio.setStyleSheet(RADIO_BUTTON_STYLE)
                button_group.addButton(radio)
                radio_buttons[option] = radio
                row_layout.addWidget(radio)
            row_layout.addStretch()
            player_rows_layout.addLayout(row_layout)
            player_controls[player.player_number] = radio_buttons
        group_layout.addLayout(player_rows_layout)
        group.setLayout(group_layout)

        self._entry_widgets.append(
            {
                "question_number": entry["question_number"],
                "original_player_states": dict(entry["player_states"]),
                "original_value": int(entry["value"]),
                "is_daily_double": bool(entry["is_daily_double"]),
                "value_input": value_input,
                "player_controls": player_controls,
            }
        )
        return group

    def collect_changes(self) -> list[dict]:
        """Return only the clue edits that differ from the saved history.

        Returns:
            List of correction payloads to apply through the game engine.
        """
        changes = []
        for widget_state in self._entry_widgets:
            updated_player_states = {
                player_index: next(
                    option
                    for option, radio in control.items()
                    if radio.isChecked()
                )
                for player_index, control in widget_state["player_controls"].items()
            }
            updated_value = (
                widget_state["value_input"].value()
                if widget_state["is_daily_double"] and widget_state["value_input"]
                else widget_state["original_value"]
            )
            if (
                updated_player_states != widget_state["original_player_states"]
                or updated_value != widget_state["original_value"]
            ):
                changes.append(
                    {
                        "question_number": widget_state["question_number"],
                        "player_states": updated_player_states,
                        "value": updated_value,
                    }
                )
        return changes
