# Hosting a JParty Game

This guide is for the person running JParty on the host machine. It focuses on what the host sees, what each startup option does, how the game flows once play begins, how to correct scores, and how to handle image clues smoothly.

For the project overview, setup, and development notes, see [README.md](README.md).
For the saved-state and clue-history file format, see
[docs/game-logging.md](docs/game-logging.md).

## Table of Contents

- [Before You Start](#before-you-start)
- [Welcome Screen Overview](#welcome-screen-overview)
- [Pre-Game Image Preview](#pre-game-image-preview)
- [Tournaments](#tournaments)
- [Resume Flow](#resume-flow)
- [Core Game Flow](#core-game-flow)
- [Editing Scores](#editing-scores)
- [Image Selection and Approval During Play](#image-selection-and-approval-during-play)
- [General Host Advice](#general-host-advice)
- [Quick Reference](#quick-reference)

## Before You Start

- Use the host machine on the main display you will control during the game.
- Put the audience board on the TV or shared screen. JParty needs two screens unless debug mode is on (see the README).
- Make sure players are on the same network as the host machine so they can join from the QR code.
- Three players is the closest to a traditional Jeopardy! game, but JParty supports fewer, or up to 6, if you want a different size of party game.

## Welcome Screen Overview

The welcome screen is your control center before the game starts.

Back to [Table of Contents](#table-of-contents).

### Game ID box

Enter a J-Archive game id here. After a short delay, JParty loads the game summary and enables the start flow when the game data is valid.

### `Start!`

Starts the loaded game. If the selected rounds contain local preloaded image clues, JParty first opens a preview screen so you can review those images before the game begins.

If you loaded a saved session, this button changes to `Resume!`.

### `Load Question Media`

Imports a folder or zip file of clue images for the currently entered game id. After import, the summary updates with a media status line such as:

- `Question media status: found folder.`
- `Question media status: found zip archive.`
- `Question media status: found folder and zip archive.`

If nothing has been imported yet, the summary can show:

- `Question media status: no folder or zip archive found.`

Use this when you want image clues prepared before the game starts rather than searching during play.

If you want a step-by-step guide for finding and naming clue images from
J-Archive, see [Saving Question Images](docs/saving-question-images.md).

### `Load Saved`

Loads an existing saved game session from disk and prepares the game to resume.

When you load a save:

- The start button becomes `Resume!`
- The saved round selection is restored
- The triple-stumper reveal setting is restored
- The summary shows the save path and reclaim status for saved players

Resume mode expects players to reclaim their saved profiles from their phones. The game will not fully start until all required saved players are claimed.

While players are reclaiming, you can still use the lobby buttons on the host scoreboard:

- `▲`/`▼` swap a player with their neighbor. Each player keeps their own saved score; only their seat (and buzzer key) changes.
- `✕` releases that player's saved slot, for example if someone claimed the wrong name. Their phone goes back to the chooser and anyone can claim that slot. Resume stays disabled until every slot is claimed again.

### `Random`

Loads a random valid game.

### Round checkboxes

Once a valid game is loaded, JParty shows `Rounds to play:` checkboxes. By default, all available rounds are selected.

Typical labels are:

- `Jeopardy!`
- `Double Jeopardy!`
- `Final Jeopardy!`

If a game has a third standard board, it is labeled `Triple Jeopardy!`.

Use these checkboxes when you want to skip a round, run a shortened game, or resume with a different subset than originally chosen.

### `Advanced Options`

This is for building a custom "Frankenstein" game from multiple boards.

When enabled, the standard single-game workflow is replaced by advanced board selection controls. You can:

- Choose how many Jeopardy boards to include
- Choose how many Final Jeopardy boards to include. Finals are played one
  after another once the standard boards are done; each Final has its own
  wagers and answers, and the winner is shown after the last one
- Fill each slot with a specific game id
- Randomize individual board slots
- Import media for an individual board source
- Select which round from that source game should fill the slot
- Customize clue values for standard boards

The summary updates to show the chosen board sources, for example which game and which round each slot came from.

If any slot is incomplete, JParty will not let you start and shows a message telling you to fill every board slot first.

### `Reveal Answers after Triple Stumper`

When enabled, a clue that nobody gets correct will pause on the answer before returning to the board. You press space once to reveal the answer and again to continue the normal flow from there.

When disabled, a triple stumper returns directly to the board after the stumped flow finishes.

### Summary warnings

The summary is worth reading before you start. It can warn about content problems in the loaded boards.

Examples include:

- Missing clue count warnings
- `CRITICAL: Missing Daily Double`

These warnings are especially useful when you are building an advanced custom board set.

## Pre-Game Image Preview

If selected rounds include local image media that was already imported, starting the game opens a preview screen instead of jumping directly into play.

Back to [Table of Contents](#table-of-contents).

That preview screen shows:

- Each local image
- The answer associated with that clue
- A `Back` button
- A `Start Game` button

Use this as a last sanity check before contestants see the board.

## Tournaments

The `Tournament` button at the bottom of the welcome screen opens the
Tournament window. Everything for a tournament happens there:

- `Create Tournament` starts a new tournament.
- `Load Tournament` opens the tournament selected under `Saved tournaments`.
  Double-clicking it works too.
- `Bracket Designer` lets you try bracket formats for any number of players,
  without saving anything. `Back to Tournaments` returns to the list.

A created or loaded tournament opens with its name and logo at the top and
three tabs: `Players`, `Bracket`, and `Games`. Everything stays editable. One
`Save` button saves all three tabs. `Close` goes back to the tournament list.
Closing the window or the tournament with unsaved changes asks before
discarding them. A tournament without unsaved changes stays open when you
close the window, so reopening the window takes you back to it.

The tournament name becomes the folder name, so it can't contain characters
like `/` or `:`. It can't be changed after the first save.

`Choose Logo...` picks the tournament logo. It is copied into the
tournament's folder when you save, so it stays out of git. `Remove Logo`
deletes it on the next save.

### Bracket rules

Every tournament ends with a three-player Final. With 9 players, three
Semifinal winners meet in the Final. With more, a first round fills the nine
Semifinal spots:

- Each game's winner advances. Leftover spots go to wildcards: the
  highest-scoring players who did not win their game.
- With `3n + 2` players, `n` regular games are played first, then one chase
  game. Its two new players advance by winning. The third seat goes to the
  chaser, the first player who would miss out on a wildcard. A chaser who wins
  opens one more wildcard spot, but their chase-game score does not count, so
  other players can still overtake their original score.
- With `3n + 1` players, there are two chase games, played one after the other.

For larger fields, turn on `Add a second round before the Semifinals`:

- `Semifinal byes`: the top-scoring preliminary players who skip the second
  round. Byes go to winners first, whether they won a regular or a chase
  game. If there are more byes than winners, the top wildcards get the rest.
- `Second-round players`: how many other players advance from the
  preliminaries. It resets to fill the remaining Semifinal spots with
  winners whenever you change the byes.

The designer shows each round's games and where every seat comes from, along
with the total games, how many players get more than one game, and how many
games the champion plays. Ranges such as `9-10` depend on whether chasers win.
If the options cannot work (for example, 28 players with no second round), the
designer explains why.

### Players tab

The `Players` tab fills the tournament's players from your Google Form
sign-up sheet.

1. Paste the link to the form's response sheet. In the sheet, choose `Share`
   and set General access to `Anyone with the link`. The sheet needs
   `Timestamp` and `Full Name` columns; `Occupation`, `Hometown`, and
   `Anecdote #1` to `#3` are saved too.
2. Set `Players` to the number of players. It can be more than the sheet has
   rows. This count also sets the bracket's size.
3. Click `Refresh Sheet`. Sign-ups fill the player slots in sheet order.
4. Edit the `Actual Name` column if someone used a silly name, and type names
   for players who haven't signed up yet.

Click `Refresh Sheet` again as more people sign up. If you've typed names that
aren't linked to a sign-up yet, JParty steps through each new sign-up and
suggests the player with the closest name. For each one, choose the player,
`A new player`, or `Not a player` for test or duplicate responses. Ignored
responses aren't asked about again. Linked players keep their Actual Name.

JParty recognizes each response by its Timestamp. If a player edits or
resubmits their response, Google gives it a new Timestamp, so JParty asks
about it on the next refresh and suggests the player it replaces (shown as
"sign-up no longer in the sheet"). Pick that player to keep their name and
update their answers.

To fix a mistake, select a row and click `Unlink Sign-up` (the sign-up is
asked about again on the next refresh) or `Remove Player`. `Restore Ignored`
makes the next refresh ask about every ignored response again.

### Bracket tab

The `Bracket` tab is the bracket designer for this tournament. The player
count comes from the `Players` tab; choose the second round and byes here.
The tab shows `Bracket (!)` while the options can't make a bracket. You can
still save, and JParty reminds you that the bracket won't work yet.

### Games tab

The `Games` tab lists every game in the bracket in playing order. Each row
shows where the game's players come from, its board, who can't play that
board, and whether the board has question media. The tab title counts the
games that have a board and the boards waiting in `Unassigned boards`, for
example `Games (3/10 boards, 2 unassigned)`.

To give a game a board, double-click the game, or select it and click
`Set Board...`. With no game selected, `Set Board...` makes a new board for
`Unassigned boards`, so you can set boards up before deciding which game gets
each one. Either way it opens the same board slots as the welcome screen's
`Advanced Options`:

1. Fill each board slot: type a game id (or click `Random`), pick its round,
   and adjust point values and Daily Doubles as you would on the welcome
   screen (see [`Advanced Options`](#advanced-options)). `Load Media` loads
   question media for a slot. Use the `Jeopardy Boards` and `Final Boards`
   counts to change how many boards the game plays.
2. Click `Use This Board`. It turns on once every slot is filled.

To play one game as it aired, type its id under `Same game for every slot`
and click `Use for Every Slot`. Each slot loads that game and picks its
matching round.

Opening a game that already has a board shows that board, so you can edit it.
The edited board replaces the old one. `Cancel` leaves the game as it was.
Setting up a tournament board doesn't change the game on the welcome screen.

To keep players off a board (for example, players who have seen that
episode or wrote its clues), select the game and click `Can't Play...`, or
double-click its `Can't Play` cell, then tick those players. The list stays
with the board: if you swap, unassign, or edit the board, the same players
still can't play it. Renaming a player keeps their place on the list, and
removing a player takes them off it when you save.

Other buttons:

- `Swap Boards`: select two games to swap their boards.
- `Unassign`: move the selected games' boards to `Unassigned boards`.
- `Assign to Selected Game`: give the selected game the selected unassigned
  board.
- `Delete Board`: remove the selected unassigned board.

If the bracket changes and a game leaves it (for example, the field shrinks
and loses a chase game), that game's board moves to `Unassigned boards`
instead of being lost. While the bracket can't work, boards stay where they
are.

The summary above the table lists games whose boards have no question media,
meaning one of the board's source games has no folder or zip in the question
media folder (see [`Load Question Media`](#load-question-media)). It also
warns when two games play the same round of the same source game, because
players would see the same clues twice.

### Saved files

Each tournament is saved in `tournaments/<name>/` in the JParty data folder,
outside git:

- `players.csv` holds the players, their sign-up answers, and an id for each
  player that other settings refer to. If you edit it by hand, leave the
  `player_id` column as it is.
- `tournament.json` holds the sheet link, the ignored responses, the bracket
  options, each game's board and who can't play it, the unassigned boards,
  and the logo's file name.
  The app writes it; you don't need to edit it by hand.
- `logo.png` (or `.jpg`, and so on) is the logo, if you chose one.

To reuse a tournament's setup, copy its folder and give the copy a new name;
the copy saves into its own folder. Tournaments saved by an older JParty
still load, with the default bracket and no boards.

Back to [Table of Contents](#table-of-contents).

## Resume Flow

Resuming is slightly different from starting fresh.

Back to [Table of Contents](#table-of-contents).

1. Click `Load Saved`.
2. Choose the saved game folder.
3. Confirm the summary looks right.
4. Wait for all saved players to reclaim their profiles on their phones.
5. Click `Resume!` once the session is startable.

On the player side, JParty presents a saved-player chooser. Each player should select their saved identity rather than creating a new one.

## Core Game Flow

Once the game starts, hosting is simple but fast-moving.

Back to [Table of Contents](#table-of-contents).

1. Click a clue on the board to open it.
2. Read the clue aloud.
3. Press `Space` to open buzzing.
4. Watch for the first contestant to buzz in.
5. Judge the response with the arrow keys.
6. Continue until the clue is resolved.
7. Advance with `Space` whenever prompted.

### Keyboard flow

The main host keys are:

- `Space`: advance the current game state
- `Left Arrow`: rule an answer correct
- `Right Arrow`: rule an answer incorrect
- `Enter`: during Final Jeopardy wagering, open the clue without waiting for
  the remaining wagers (see [Final Jeopardy](#final-jeopardy))

Holding a key down counts as one press, so a long press of `Space` only
advances one step.

In practice, `Space` is reused throughout the game for things like:

- Opening the buzz window after you finish reading
- Returning to the board
- Revealing a stumped answer if that option is enabled
- Moving to the next round
- Opening Final Jeopardy
- Stepping through Final Jeopardy judging

### Buzzing and judging

After you press `Space`, players can buzz.

- If a player buzzes first, JParty highlights that player and waits for your ruling.
- `Left Arrow` awards the clue and returns to the board.
- `Right Arrow` deducts the clue value and usually reopens play for rebounds if eligible.

If nobody gets the clue:

- JParty runs the stumped flow
- If triple-stumper reveal is enabled, the answer is shown before you go back
- Otherwise the game returns directly to the board

### Daily Doubles

When a Daily Double appears:

1. JParty shows the Daily Double splash.
2. On the host display, click the player who found it.
3. Enter that player's wager.
4. The clue is shown.
5. Judge the answer with the arrow keys as usual.

While JParty is waiting for you to choose the Daily Double player, podium hover and clicks are part of the clue flow, not score editing.

### Final Jeopardy

At the end of the selected standard rounds, JParty moves into Final Jeopardy.

The general flow is:

1. Players submit wagers.
2. Press `Space` to reveal the clue.
3. Press `Space` again to open final responses.
4. After response entry, JParty steps through players for judging.
5. Press `Space` to move through each reveal stage.
6. Use `Left Arrow` or `Right Arrow` to judge each response.

JParty judges Final Jeopardy responses in score order, starting from the lowest score.

If a player can't wager (their phone died, they left, or they are not really
playing), press `Enter` while JParty is waiting for wagers. The clue opens
right away and every missing wager counts as $0. Wagers already sent are kept,
and a wager that arrives after you press `Enter` is ignored.

## Editing Scores

JParty supports two different kinds of score correction.

Back to [Table of Contents](#table-of-contents).

### `Edit Score` button

The host scoreboard has an `Edit Score` button that opens a correction dialog for recent clue history.

Use it when you need to fix a ruling from a recently played clue. The dialog shows up to the previous five played clues and includes:

- Category
- Clue value
- Correct response
- One selector per player

Each player's result can be changed to:

- `No Answer`
- `Correct`
- `Incorrect`

For Daily Doubles, the dialog also exposes the wager so you can fix an incorrect amount. It allows the same range as the wager prompt during the game: $5 up to the player's score before that clue or the board's top clue value, whichever is larger. A saved wager outside that range (from an older save) is kept as it is unless you change it.

Saving these changes records a correction in the saved clue history and adjusts the affected players' scores, which is much better than manually patching a total when the real problem was an earlier ruling.

The `Edit Score` button is disabled when:

- A clue is currently active
- JParty is waiting for Daily Double player selection
- There is no recent clue history yet

### Clicking a player's podium

When a game is running and no clue is active, clicking a player's podium opens a manual score override flow for that player. Podium clicks do nothing in the lobby, before Start or after Close Game, because there is no game to save the change in.

Use this when:

- You need a one-off manual adjustment
- You are fixing something outside the recent-history window
- You intentionally want to set a total directly

Manual overrides are saved in the game history too, so resumed games preserve the corrected total.

### Which score tool should you use?

Prefer `Edit Score` when the problem was a wrong ruling on a recent clue. Prefer a direct podium edit when you truly want to set a player's total manually.

If you need the exact save-file and log structure behind those corrections, see
[docs/game-logging.md](docs/game-logging.md).

## Image Selection and Approval During Play

Some clues require host review before they are shown as image clues.

Back to [Table of Contents](#table-of-contents).

When that happens, the host sees an image review screen with:

- The proposed image
- A search box
- An accept button
- A reject / no-image-needed button

### Search box behavior

You can either:

- Paste a direct image URL
- Enter a search query

Search queries use Wikimedia lookup. This is useful when J-Archive indicates an image-based clue but the exact image still needs host approval.

### If the image is right

Accept the image. JParty marks the clue as an image clue and stores the approved image locally when possible so contestant displays use a stable local file.

### If the image is wrong or unnecessary

Choose the no-image-needed path. JParty clears the image requirement for that clue and continues loading it as a normal text clue.

### Best practice

If you know a game has many visual clues, import question media before the game and use the pre-game preview. It is much smoother than searching live while contestants wait.

## General Host Advice

- If you are unsure if an answer is correct, rule it wrong to give other players a chance to respond. We can always amend after the question.
- When in doubt, press the space bar.
- Try to be consistent in your reading speed and question completion to space bar press. 

## Quick Reference

Back to [Table of Contents](#table-of-contents).

- Click board clue: open clue
- `Space`: open buzz / advance state
- `Left Arrow`: correct
- `Right Arrow`: incorrect
- `Enter` while waiting for Final wagers: open Final, missing wagers count as $0
- `Edit Score`: fix recent clue rulings
- Click podium with no active clue: manual score override
- `Load Question Media`: import clue images for a game id
- `Load Saved`: resume an earlier session
- `Advanced Options`: build a mixed-source custom game
