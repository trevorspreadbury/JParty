"""Host-side widgets for editing recent score history."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

RESULT_OPTIONS = ("no answer", "correct", "incorrect")


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

        form_layout = QFormLayout()
        player_controls = {}
        for player in self.players:
            combo = QComboBox(group)
            combo.addItems(list(RESULT_OPTIONS))
            combo.setCurrentText(
                entry["player_states"].get(player.player_number, "no answer")
            )
            form_layout.addRow(player.name, combo)
            player_controls[player.player_number] = combo
        group_layout.addLayout(form_layout)
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
                player_index: control.currentText()
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
