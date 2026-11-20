# Hosting a JParty Game

This guide is for the person running JParty on the host machine. It focuses on what the host sees, what each startup option does, how the game flows once play begins, how to correct scores, and how to handle image clues smoothly.

For the project overview, setup, and development notes, see [README.md](README.md).
For the saved-state and clue-history file format, see
[docs/game-logging.md](docs/game-logging.md).

## Table of Contents

- [Before You Start](#before-you-start)
- [Setting Up Lecterns](#setting-up-lecterns)
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

## Setting Up Lecterns

Lecterns are optional screens, one per player, that show the player's name,
score, buzz-in lights and countdown. Each one is a web page, so any computer
on the same network can show it. A common setup is a laptop behind each
lectern, connected to a monitor.

A lectern page can be left open all evening. It reconnects by itself when
JParty restarts or the Wi-Fi drops, shows the logo while its seat is empty,
and never needs a refresh.

### Open the lectern page

On each lectern laptop, open `http://<address>/lectern` in a browser, where
`<address>` is the address shown on the JParty welcome screen (for example
`http://192.168.1.20:8080/lectern`). Every lectern can use the same address.

The first time, the page asks which lectern it is. Press `1` to `6` on the
laptop's keyboard. The browser remembers the choice, so next time the same
address opens the same lectern.

### Lectern keys

Everything works from the keyboard, so you don't have to find the mouse:

| Key | What it does |
|-----|--------------|
| `F` | Full screen on or off |
| `R` | Turn the lectern a quarter turn clockwise (`Shift+R` turns it back) |
| `1` to `6` | Change which lectern this screen shows |
| `H` or `?` | Show which lectern this is and these keys |

The mouse cursor hides itself after two seconds.

### Monitors on their side (portrait)

You don't need to change the laptop's display settings for a monitor mounted
on its side. Leave the display as it is and press `R` until the lectern is
upright. The page remembers the rotation.

You can also put the seat and rotation in the address, which is handy for the
kiosk commands below:

- `player=0` to `player=5`: the seat, counting from 0 (`player=0` is lectern 1)
- `rotate=90`, `rotate=180`, `rotate=270`, or `rotate=right` / `rotate=left`
  (a quarter turn clockwise or counterclockwise)

For example: `http://192.168.1.20:8080/lectern?player=1&rotate=right`.

### Show only the external monitor

If a lectern laptop shows a picture on both its own screen and the monitor,
the mouse and browser windows can end up on the screen you can't see. Set
each laptop to use only the monitor:

- **Windows:** press `Win+P` and choose **Second screen only**. To close the
  lid without the laptop going to sleep, open Control Panel → Power Options →
  **Choose what closing the lid does**, and set **Plugged in** to
  **Do nothing**.
- **macOS:** with the power adapter connected, close the lid. Some Macs also
  need an external keyboard or mouse connected to keep using the monitor with
  the lid closed. You can also mirror the displays instead (System Settings →
  Displays): because the lectern page does the rotating, both screens can stay
  in landscape.
- **Ubuntu:** press `Super+P` until only the external display is used, or
  choose **Single Display** in Settings → Displays. With a monitor connected
  and the power plugged in, closing the lid usually keeps it running. If it
  goes to sleep instead, set `HandleLidSwitchExternalPower=ignore` in
  `/etc/systemd/logind.conf` and restart.

### Start in kiosk mode (optional)

A browser started in kiosk mode opens straight into full screen, with no
address bar, and stays that way. Close the browser before running the
command. If it is already open, the command may open an ordinary window
instead. Change the address to match your welcome screen, and add `player=`
or `rotate=` if you like.

- **Windows** (Microsoft Edge). In Command Prompt, run:

  ```bat
  start "" msedge --kiosk "http://192.168.1.20:8080/lectern" --edge-kiosk-type=fullscreen --no-first-run --user-data-dir=%USERPROFILE%\jparty-lectern
  ```

  For Chrome, use `chrome` instead of `msedge` and leave out
  `--edge-kiosk-type=fullscreen`.
- **macOS** (Google Chrome). In Terminal, run:

  ```bash
  open -na "Google Chrome" --args --kiosk --no-first-run --user-data-dir="$HOME/jparty-lectern" "http://192.168.1.20:8080/lectern"
  ```

  Safari has no kiosk mode. Open the page and press `F` instead.
- **Ubuntu** (Firefox comes with Ubuntu). In a terminal, run:

  ```bash
  firefox --kiosk "http://192.168.1.20:8080/lectern"
  ```

  For Chrome or Chromium, use
  `google-chrome --kiosk --user-data-dir="$HOME/jparty-lectern" "http://192.168.1.20:8080/lectern"`
  (or `chromium` instead of `google-chrome`).

The `--user-data-dir` option gives the lectern its own browser profile, so it
starts in kiosk mode even if you use the same browser for other things. To
leave kiosk mode, press `Alt+F4` (Windows and Ubuntu) or `Cmd+Q` (macOS).

### Keep the laptops awake

A lectern that goes to sleep or turns its screen off goes dark mid-game. On
each lectern laptop, plug in the power and turn off sleep and screen
blanking:

- **Windows:** Settings → System → Power → **Screen and sleep**: set the
  plugged-in options to **Never**. Or run
  `powercfg /change monitor-timeout-ac 0` and
  `powercfg /change standby-timeout-ac 0`.
- **macOS:** run `caffeinate -d` in Terminal and leave that window open while
  you play (press `Ctrl+C` to stop it).
- **Ubuntu:** Settings → Power: set **Screen Blank** to **Never** and turn off
  **Automatic Suspend** when plugged in. Or run
  `gsettings set org.gnome.desktop.session idle-delay 0` and
  `gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'`.

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
four tabs: `Players`, `Bracket`, `Games`, and `Rankings`. Everything but the
rankings stays editable. One `Save` button saves the first three tabs. `Close` goes back to the tournament list.
`Play Games` saves if needed and hands the tournament to the welcome screen;
see [Playing tournament games](#playing-tournament-games).
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
  chaser, the first player who would miss out on a wildcard after the regular
  games. A chaser who wins opens one more wildcard spot, but their chase-game
  score does not count, so other players can still overtake their original
  score.
- With `3n + 1` players, there are two chase games. Both chasers are set once
  the regular games are done: the second player out chases in Chase 1, and the
  first player out in Chase 2. The second player out only gets in if both
  chasers win, so they go first; if they lose, Chase 2 still matters to the
  first player out. The regular games need two non-winners outside the
  wildcards for this, so some second-round settings aren't allowed.

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
still save, and JParty reminds you that the bracket won't work yet. If the
field drops to 9 or fewer players, the second round turns off; it turns back
on if the field grows again.

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
and click `Use for Every Slot`. The slots go back to two boards and Final
Jeopardy! with the usual values and Daily Doubles, then each loads that game
and picks its matching round.

Opening a game that already has a board shows that board, so you can edit it.
The edited board replaces the old one. `Cancel` leaves the game as it was.
Setting up a tournament board doesn't change the game on the welcome screen.

To keep players off a board (for example, players who have seen that
episode or wrote its clues), select the game and click `Can't Play...`, or
double-click its `Can't Play` cell, then tick those players. For a board in
`Unassigned boards`, select it and click the `Can't Play...` button next to
`Assign to Selected Game`, or double-click the board. The list stays
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
instead of being lost. If the game comes back before you close the
tournament (for example, the player count changes back) and it has no board,
the board returns to it. While the bracket can't work, boards stay where they
are.

The summary above the table lists games whose boards have no question media,
meaning one of the board's source games has no folder or zip in the question
media folder (see [`Load Question Media`](#load-question-media)). It also
warns when two games play the same round of the same source game, because
players would see the same clues twice.

Once a game has been played, its board is locked: `Set Board...`, `Swap
Boards`, `Unassign`, and `Assign to Selected Game` no longer change it, and
its board shows `(played)`. A Bracket or Players change that would drop a
played game warns you, and the tournament can't be saved that way: change
it back, or delete that game's results with `Fix Results...` first.

Before game day:

- `Download All Games` loads every board, including the unassigned ones, and
  saves their J-Archive games on this computer, so the tournament can be
  played without the internet. It counts the boards that are ready and lists
  any that couldn't load. Google Sheets games are checked, but they still
  load from the sheet when played.
- `Preview All Media...` loads every board the same way, then shows each
  board's question media with its category, value, and correct response, so
  you can check the images before anyone sees them. Boards with no question
  media, or that couldn't load, say so. If you close the Tournament window
  or click `Play Games` while the boards load, the preview doesn't open by
  itself; click `Preview All Media...` again when you're back.

### Rankings tab

The `Rankings` tab ranks every player from the saved results. The champion
comes first, then players by the furthest round they've reached (playing in
a round, advancing into it, or skipping to it with a bye all count). Within a
round, players still in the tournament come before players who are out, and
then the higher score in their latest round goes first. Players level on all
of that share a place. Players who haven't played yet are listed last
without a place. Each row also shows where the player stands, their games
played, and their total, best, and Coryat scores. Players who are out are
greyed out.

### Playing tournament games

`Play Games` in a tournament puts the welcome screen into tournament mode.
The game id box, round checkboxes, and `Advanced Options` are replaced by
the tournament's games and players. `Reveal Answers after Triple Stumper` is
hidden and always on for tournament games, so every game is played the same
way; leaving the tournament puts your choice back.

1. Pick a game from `Games`. Its board loads by itself, and its summary
   shows below. Games already played, and games with no board, are greyed
   out and can't be picked.
2. Pick a player for each podium. Only players who can play that game are
   offered:
   - A first-round game: anyone who hasn't played that round yet.
   - A later round: the players who advanced into it (see
     [Advancement](#advancement)) and haven't played it yet. Until the round
     before is decided, no one is offered, and the status line says why.
   - A chase game: two new players, and the round's chaser (marked
     `(chaser)`, and shown next to the game in `Games`).
   - Players on the board's Can't Play list are never offered.
3. Have the three players join from their phones as usual. Each podium shows
   the phone on it: the typed name, or the signature a player signed in with. Podium 1 is the first phone in the scoreboard, and so
   on; use the scoreboard's `▲`/`▼` to put the phones in podium order.
4. Click `Start!`. The host screen shows "Let's meet today's contestants:"
   and an introduction for each player, such as "A teacher from Chicago,
   Jane Smith (Ziggy)". The name appears once when the sheet's Full Name
   and the Actual Name match, and a player with no sign-up is introduced by
   their Actual Name. Click `Start Game` to begin (`Back` returns to the
   welcome screen). If another phone joins while the introduction is
   showing, `Start Game` goes back to the welcome screen, and the status
   line says what's wrong; remove the extra phone, or use `▲`/`▼` to fix
   the order. A phone that drops keeps its podium and rejoins it when it
   reconnects.

When the game ends, after Final Jeopardy or a tiebreaker, its results are
saved to the tournament's `results.csv`. A tie for first has to be settled
by a tiebreaker before the results are saved. Back on the welcome screen, the
game is greyed out, and `Players` shows where each of its players stands (see
[Advancement](#advancement)).

A tournament game that stopped part way through (for example, the app
closed) shows `(in progress)` in `Games`. Its tooltip names the players it
started with. To pick it up where it stopped, select it and click `Resume
Saved Game`: `Start!` becomes `Resume!`, and each player's phone claims their
saved player as it would after `Load Saved`. `Resume!` turns on once every
saved player is claimed, and skips the introduction. Selecting another game
drops the resume. If one of the saved players has dropped out, or can no
longer play that game, `Resume Saved Game` stays off and the status line says
why, since the game's results would be logged for them; start the game again
with new players, or undo the drop. A resumed game still saves its results
when it ends. You can also start an in-progress game again from the
beginning by picking its players and clicking `Start!` as usual.

The regular `Load Saved` button checks a tournament game's save the same
way, and also checks whether the game already has results from another
save (for example, an abandoned start of a game that was then replayed).
A save that fails a check still resumes, but as a regular game: a warning
says why, and its results aren't saved to the tournament. When any
tournament game ends, its results are also not saved over another save's
results for that game, or for a player who has dropped out; a warning says
so instead. Use `Fix Results` if those results should count.

`Rankings...` shows the same rankings as the Tournament window's
[Rankings tab](#rankings-tab). `Edit Tournament...` opens this tournament in
the Tournament window to change its players, bracket, or boards. Saving
there updates the games and players here straight away, unless a game is
being played; then they update when you return to the welcome screen.
`Fix Results...` opens the saved results. You can change scores, Coryat
scores, and who won (each game needs a winner), or use `Delete Game's
Results` so a game can be played again. `Leave Tournament` returns to
choosing a regular game.

### Advancement

JParty works out who advances from `results.csv` each time, so a fixed
result changes it right away. `Players` shows where each player is, such as
`(won, in the Semifinals)`, `(wildcard, in the Semifinals)`, `(bye to the
Semifinals)`, `(chaser in Chase 1)`, `(out)`, or `(champion)`. Players who
are out, or who are waiting for the rest of their round, are greyed out.

- Every game's winner advances.
- A round's leftover spots go to wildcards: the players who didn't win
  their game, by highest final score.
- A chase game's third seat goes to the chaser: the first player who would
  miss out on a wildcard once the round's regular games are played. With two
  chase games, Chase 1 is for the second player out and Chase 2 for the
  first, and they can be played in either order. A chaser who wins doesn't
  advance directly; the win opens one more wildcard spot, ranked on
  everyone's first score of the round, so the chaser's chase-game score
  doesn't count.
- With a second round, the top-scoring preliminary winners get byes to the
  Semifinals. If there are more byes than winners, the top wildcards get
  the rest.

Players tied on score for the last wildcard spot, a chaser seat, or the
last bye need a tiebreaker. Until it's played, the next game can't start,
and the status line says who is tied. A tie that only decides seeding, not
who gets in, goes to the higher Coryat score instead: for example, two
chasers level on score both chase, and the one with the better Coryat is the
first player out (so plays Chase 2). If their Coryat scores are level too, or
unknown, it's a tiebreaker. To play it:

1. Pick the tie at the top of `Games`, such as `Tiebreaker: Eve, Fay for
   the last wildcard spot in the Quarterfinals`. The podiums show the tied
   players in the order their phones join.
2. Have the tied players join from their phones, in that order. `Start!`
   turns on once there is one phone per tied player.
3. Click `Start!`. There's no board or introduction: the screen shows the
   tie, and the tiebreaker plays as after a tied Final (see
   [Tiebreaker](#tiebreaker)). `Cancel` on the game id prompt goes back to
   the tournament without settling the tie.
4. When someone wins, the win is saved, and `Space` returns to the welcome
   screen with the tie settled.

If several players are tied for more than one spot, each tiebreaker settles
one spot; play the next one for the players still tied.

If a fixed result means someone who already played a later game no longer
advanced into it, or a chase game was played by someone who shouldn't have
chased, a red warning above `Games` lists them. Fix that game's results too,
or delete them and play it again. A chase game whose chaser already chased
in the other chase game waits until the results are sorted out. A chase
game played before all of its round's regular games (for example after a
regular game's results were deleted) is listed too: delete it, and play it
again once the regular games are played.

### Dropouts

A player can drop out at any time. Select them in `Players` and click `Drop
Player...`. The dialog says where they stand and what can happen to their
spot. Your choice is saved straight away, and the player shows as `(dropped
out)` and can't be picked again. What happens depends on how far they got:

- **Before their first game**, choose one:
  - `Reduce the field`: the games not yet played are planned again for one
    fewer player, and games already played stay as played. This can turn a
    regular game into a chase game, for example. Boards of games that go away
    go back to unassigned. If the smaller bracket doesn't work, or doesn't
    have a game that's already been played, this choice is greyed out.
  - `Replace them with a new player`: type the new player's name. They join
    the roster and play in the dropped player's place. Link their sign-up on
    the `Players` tab if they have one.
- **After their first game, before they win a Semifinal**, everyone ranked
  beneath them in the last round they played moves up a place. If they won
  their game, that round gets one more wildcard. A chaser who hasn't played
  their chase game yet is worked out again, so the next player out may chase
  instead. A chase game that was already played keeps its chaser, and
  someone who already chased isn't asked to chase again.
- **A Semifinal winner** who drops out has their Semifinal voided: its
  results move to `voided_results.csv`, its board is retired so it isn't
  played again, and the game is played again with a new board. Set the new
  board on the `Games` tab. The next-ranked player of the round before the
  Semifinals (the Second Round, if there is one) takes the dropped player's
  seat. When the Semifinals are the first round, the best player from the
  other Semifinals who didn't win takes it, marked `(replacement)` on the
  podiums; the replay waits until the other Semifinals have been played, so
  that player is known. They can't drop out once the Final has been played. This case
  isn't fully worked out yet: the dropout rules are meant for brackets with
  three or more rounds, and with only the Semifinals and the Final (4 to 9
  players) the replacement has played two Semifinals. With 4 to 8 players,
  where the Semifinals also send a wildcard to the Final, check the Final's
  players by hand.
- **A player with a Semifinal bye**: if no Second Round game has been played
  yet, the Preliminaries move up as above, so the best remaining winner gets
  the bye and the next player gets a Second Round seat. Once a Second Round
  game has been played, choose one:
  - `Add a play-in game`: the next three Preliminaries players play a new
    game, `Play-in 1`, in the Second Round. Its winner takes the bye's seat
    in the Semifinals. Set its board on the `Games` tab.
  - `Promote a waiting player`: the best-ranked Second Round player who
    hasn't played yet gets the bye, and the next Preliminaries player takes
    their Second Round seat. Winners come first, then wildcards, each by
    Preliminaries score. If the best waiting players are tied, a tiebreaker
    between them decides who is promoted.

Ties for these spots, such as two players level for a dropped player's
seat, are settled with a tiebreaker like any other.

Some brackets (such as 11 or 13 players) have no spare players: every
regular-game player who doesn't win is a wildcard or a chaser. If one of them
drops out before the chase game, everyone moves up and there's no one left
to chase. The chase game is then played by its two new players alone, for
its one spot: pick them, leave the third podium empty, and start with two
phones.

A choice is greyed out, with the reason, if it would leave a seat that
nobody can fill: for example a play-in game with fewer than three players
left to play it, or more players dropping out of a round than it knocks out,
so no one is left to move up. This is checked as soon as the player drops
out, even if the round isn't finished. `Undo Drop...` is refused for the
same reason.

`Undo Drop...` takes a dropout back, for example if it was a mistake. A
voided Semifinal gets its results back, and its board if it has no new one,
as long as it hasn't been played again. A replacement player stays on the
roster; remove them on the `Players` tab if they aren't needed.

Dropping a player out changes the roster and boards, so first save or
discard any unsaved changes in the Tournament window.

### Host phone page

While you play a tournament, open `http://<address>/host` on your phone,
where `<address>` is the address shown on the JParty welcome screen (for
example `http://192.168.1.20:8080/host`). It shows one player at a time:
their name, how to introduce them (the same line the host screen shows),
and their sign-up anecdotes.

- During a game, it steps through that game's players in reverse seat
  order: the last podium first. With no game in progress, it steps through
  every player. Use `Previous` and `Next` to move between them.
- Tick the box next to an anecdote once you've used it. It's saved straight
  away and stays ticked (and crossed out) for the rest of the tournament, so
  you can pick a fresh one next time. Untick it to use it again.
- Tap `Refresh` (or reload the page) after a game starts or ends; the page
  doesn't update by itself. It stays on the player you were looking at.
- It shows the tournament chosen with `Play Games`, or the tournament of a
  saved tournament game you resumed. Outside a tournament it says so.

You don't need to type the address: in a tournament game, when you finish
the first board and press `Space`, your host screen shows a QR code for the
page instead of the next board (the audience screen doesn't change). Scan it
with your phone, then press `Space` again for the next board. It's shown
once per game.

Anyone on the same network can open the page and tick anecdotes, like the
buzzer page, so keep
sign-up answers to things players are happy for others to see.

### Saved files

Each tournament is saved in `tournaments/<name>/` in the JParty data folder,
outside git:

- `players.csv` holds the players, their sign-up answers, and an id for each
  player that other settings refer to. If you edit it by hand, leave the
  `player_id` column as it is.
- `tournament.json` holds the sheet link, the ignored responses, the bracket
  options, each game's board and who can't play it, the unassigned boards,
  the boards of voided games, and the logo's file name.
  The app writes it; you don't need to edit it by hand.
- `logo.png` (or `.jpg`, and so on) is the logo, if you chose one.
- `results.csv` has one row per player per played game: `player` (Actual
  Name), `score`, `coryat`, `game` (`<tournament name>-<game id>`, where the
  game id is the board's id, as in the saved game's folder name), and
  `result` (`win` or `loss`). The `player_id`, `game_key`, and `saved_game`
  columns after them are what JParty matches on; leave them as they are if
  you edit the file by hand. Saving the tournament's setup never changes it.
  If you edit it in Excel, save it as "CSV UTF-8" with commas between cells.
  JParty won't play a game while it can't read the file, so a game can't
  overwrite results it couldn't read. `Fix Results...` reads it again once
  it's fixed.
- `tiebreaks.csv` has one row per tiebreaker played to settle a tie:
  `round`, `winner_name`, `winner` (the winner's player id), and `players`
  (the tied players' ids, separated by spaces). Playing the same tie again
  replaces its row. To play a tie again, delete its row.
- `dropouts.csv` has one row per player who dropped out: `player_name`,
  `round`, `choice` (`reduce`, `replace`, `slide`, `void`, `play_in`, or
  `promote`), and the ids JParty matches on (`player_id`, then `game_key`
  for a voided or play-in game and `other_id` for a replacement or promoted
  player). Use `Undo Drop...` rather than editing it.
- `voided_results.csv` keeps the results of voided Semifinals, in the same
  columns as `results.csv`. They don't count toward anything.
- `used_prompts.csv` lists the anecdotes you've ticked on the host phone
  page: `player_id`, `prompt` (the anecdote's number), and `text`.

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

Some J-Archive categories come with a hint from the TV host, such as
"(Ken: Each response ends in -ing.)". The host screen shows it in gold
italics under the category name, so you can read it out when the category
comes up. The audience screen doesn't show it. Final Jeopardy and
tiebreaker categories show their hint too, until you reveal the clue.

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

### Tiebreaker

If two or more players finish tied for first, at any score (including $0
or below), JParty shows the tie and offers a tiebreaker.

1. Press `Space`. JParty asks for a J-Archive game ID to take the
   tiebreaker clues from. Leave it blank for a random game, or press
   `Cancel` to end the game in a tie. A tournament game can't end in a
   tie, so there `Cancel` goes back to the tie screen.
2. JParty loads that game in the background and picks its highest-value
   clues, in random order. Lower-value clues are only used once the top ones
   run out. Final Jeopardy, blank clues, and image clues are skipped.
3. The category is shown first, like Final Jeopardy. Press `Space` to show
   the clue, then read it and press `Space` again to open buzzing.
4. Only the tied players can buzz. Their phones show the buzz button again;
   everyone else's phone says they are sitting out. Judge with `Left Arrow`
   or `Right Arrow` as usual. A miss reopens buzzing for the other tied
   players.
5. The first correct response wins the game. If nobody gets the clue,
   press `Space` for the next one (after revealing the answer, if
   triple-stumper reveal is on).

Tiebreaker rulings never change a score. The scores stay tied, and the
end-of-game summary names the tiebreaker winner. Each tiebreaker clue is
saved in the game's clue history; see
[Game Logging](docs/game-logging.md#tiebreaker-clues-and-tiebreaker_clue). If the game runs out of
clues or can't be loaded, press `Space` to pick another game.

Once a tie is offered a tiebreaker, scores are locked: `Edit Score` and
podium clicks stay off until you close the game. Fix any ruling that caused
the tie before the game ends.

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
- The game ended in a tie for first (see [Tiebreaker](#tiebreaker))

### Clicking a player's podium

When a game is running and no clue is active, clicking a player's podium opens a manual score override flow for that player. Podium clicks do nothing in the lobby, before Start or after Close Game, because there is no game to save the change in. They also do nothing once a tie for first has been offered a tiebreaker.

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
- `Space` after a tie for first: start a tiebreaker from another game
- `Edit Score`: fix recent clue rulings
- Click podium with no active clue: manual score override
- `Load Question Media`: import clue images for a game id
- `Load Saved`: resume an earlier session
- `Advanced Options`: build a mixed-source custom game
