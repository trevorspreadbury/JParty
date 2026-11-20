"""Tournament rules: pure functions over plain tournament data.

Widgets call these; they don't decide who plays, advances, or may resume.

- :mod:`.roster`: player slots and the Google Form sign-ups linked to them
- :mod:`.bracket`: bracket planning (qualifying rounds, wildcards, chase
  games, the optional second round and its byes)
- :mod:`.setup`: bracket settings, each game's board, and ``game_key``
- :mod:`.advancement`: who advances, chasers, byes, tiebreakers, and seating
- :mod:`.dropouts` and :mod:`.drop_choices`: dropout records and the host's
  choices for them
- :mod:`.play`: result rows and player introductions
- :mod:`.rankings`: rankings
- :mod:`.saves`: saved games of half-played tournament games
- :mod:`.host`: the ``/host`` phone page's data
- :mod:`.store`: reading and writing the tournament folder
"""
