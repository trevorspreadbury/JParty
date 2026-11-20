"""Dialogs for marking a tournament player as dropped out, and taking it back.

:class:`DropPlayerDialog` shows where a player stands and the host's
choices (see :mod:`jparty.domain.tournament.drop_choices`).
:class:`UndoDropDialog` lists the dropouts so one can be taken back.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.tournament.drop_choices import DropOption, DropSituation
from jparty.domain.tournament.dropouts import DROP_REPLACE, Dropout

LAYOUT_SPACING = 8
PROBLEM_STYLE = "QLabel { color: #b00020; }"


class DropPlayerDialog(QDialog):
    """Choose what happens when a player drops out.

    Attributes:
        situation: Where the player stands, and the choices.
    """

    def __init__(self, situation: DropSituation, parent: QWidget | None = None) -> None:
        """Show ``situation``'s choices, with the first open one picked.

        Args:
            situation: The player's situation, from
                :func:`jparty.domain.tournament.drop_choices.drop_situation`.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.situation = situation
        self.setWindowTitle("Drop Player")
        self.group = QButtonGroup(self)
        self.radios: list[QRadioButton] = []
        layout = QVBoxLayout(self)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING * 2,) * 4)
        layout.setSpacing(LAYOUT_SPACING)
        summary = QLabel(situation.summary, self)
        summary.setWordWrap(True)
        layout.addWidget(summary)
        for index, choice in enumerate(situation.options):
            radio = QRadioButton(choice.label, self)
            radio.setEnabled(not choice.problem)
            self.group.addButton(radio, index)
            self.radios.append(radio)
            detail = QLabel(choice.problem or choice.detail, self)
            detail.setWordWrap(True)
            if choice.problem:
                detail.setStyleSheet(PROBLEM_STYLE)
            detail.setContentsMargins(LAYOUT_SPACING * 3, 0, 0, 0)
            layout.addWidget(radio)
            layout.addWidget(detail)
        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("New player's Actual Name")
        layout.addWidget(self.name_edit)
        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(PROBLEM_STYLE)
        layout.addWidget(self.status_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Drop Player")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.group.idToggled.connect(lambda *_args: self._update())
        for radio in self.radios:
            if radio.isEnabled():
                radio.setChecked(True)
                break
        self._update()

    def chosen(self) -> DropOption | None:
        """Return the picked choice, or ``None``."""
        index = self.group.checkedId()
        if not 0 <= index < len(self.situation.options):
            return None
        return self.situation.options[index]

    def new_player_name(self) -> str:
        """Return the replacement's name, as typed."""
        return self.name_edit.text().strip()

    def accept(self) -> None:
        """Close if the choice is complete; a replacement needs a name."""
        problem = self._problem()
        if problem:
            self.status_label.setText(problem)
            return
        super().accept()

    def _problem(self) -> str:
        """Return why the dialog can't be accepted yet, or ``""``."""
        chosen = self.chosen()
        if chosen is None:
            return "Choose what happens to their spot."
        if chosen.dropout.choice == DROP_REPLACE and not self.new_player_name():
            return "Type the new player's name."
        return ""

    def _update(self) -> None:
        """Show the name box only for a replacement."""
        chosen = self.chosen()
        self.name_edit.setVisible(
            chosen is not None and chosen.dropout.choice == DROP_REPLACE
        )
        self.status_label.setText("")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            chosen is not None
        )


def ask_drop(
    situation: DropSituation, parent: QWidget | None
) -> tuple[DropOption, str] | None:
    """Ask the host what happens to a dropped player's spot.

    Args:
        situation: The player's situation.
        parent: The dialog's parent.

    Returns:
        The choice and any new player's name, or ``None`` if cancelled.
    """
    dialog = DropPlayerDialog(situation, parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    chosen = dialog.chosen()
    name = dialog.new_player_name()
    dialog.deleteLater()
    if not accepted or chosen is None:
        return None
    return chosen, name


class UndoDropDialog(QDialog):
    """Pick a dropout to take back."""

    def __init__(
        self,
        dropouts: Sequence[Dropout],
        texts: Sequence[str],
        problems: Sequence[str],
        parent: QWidget | None = None,
    ) -> None:
        """List the dropouts, with any reason one can't be taken back.

        Args:
            dropouts: Every dropout.
            texts: A description of each.
            problems: Why each can't be taken back, or ``""``.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.dropouts = list(dropouts)
        self.problems = list(problems)
        self.setWindowTitle("Undo Drop")
        self.list = QListWidget(self)
        for text, problem in zip(texts, problems, strict=True):
            item = QListWidgetItem(text + (f" ({problem})" if problem else ""))
            self.list.addItem(item)
        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(PROBLEM_STYLE)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Undo Drop")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(LAYOUT_SPACING * 2,) * 4)
        layout.addWidget(QLabel("Choose a dropout to take back:", self))
        layout.addWidget(self.list, 1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.buttons)
        if self.dropouts:
            self.list.setCurrentRow(len(self.dropouts) - 1)

    def chosen(self) -> Dropout | None:
        """Return the selected dropout, or ``None``."""
        row = self.list.currentRow()
        return self.dropouts[row] if 0 <= row < len(self.dropouts) else None

    def accept(self) -> None:
        """Close if the selected dropout can be taken back."""
        row = self.list.currentRow()
        if not 0 <= row < len(self.dropouts):
            self.status_label.setText("Choose a dropout.")
            return
        if self.problems[row]:
            self.status_label.setText(self.problems[row])
            return
        super().accept()


def ask_undo(
    dropouts: Sequence[Dropout],
    texts: Sequence[str],
    problems: Sequence[str],
    parent: QWidget | None,
) -> Dropout | None:
    """Ask the host which dropout to take back.

    Args:
        dropouts: Every dropout.
        texts: A description of each.
        problems: Why each can't be taken back, or ``""``.
        parent: The dialog's parent.

    Returns:
        The dropout, or ``None`` if cancelled.
    """
    dialog = UndoDropDialog(dropouts, texts, problems, parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    chosen = dialog.chosen()
    dialog.deleteLater()
    return chosen if accepted else None
