"""User-facing instructional text shown within the application.

This module stores the built-in help copy that explains basic JParty controls
and a few Jeopardy gameplay conventions. Keeping the text isolated here makes
it easy for the UI to reuse and update without mixing presentation copy into
widget code.
"""

helpmsg = '\nWelcome to JParty!\n\n- Click on the game board to display each question.\n- Press space immediately after reading the clue.\n- Adjudicate with the arrow keys.\n- Use the space bar to move through the rest of the game.\n\nSome general Jeopardy rules:\n- Answering correctly gives you control of the board.\n- Contestants must answer in the form of a question ("who is?" or "what is?").\n    '
