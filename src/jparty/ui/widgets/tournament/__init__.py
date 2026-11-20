"""Tournament widgets: the setup window and the welcome screen's play panel.

These widgets show tournament data and call the rules in
:mod:`jparty.domain.tournament`; they don't decide who plays or advances.

- :mod:`.window`: the Tournament window, holding a :mod:`.editor` per
  tournament with its :mod:`.roster`, :mod:`.bracket`, :mod:`.games`,
  :mod:`.prep`, and :mod:`.rankings` tabs
- :mod:`.board_setup`: the dialog that picks a tournament game's board
- :mod:`.play` and :mod:`.dropouts`: the welcome screen's play panel and
  its dropout dialogs
"""
