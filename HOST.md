# Hosting a JParty Game

This guide is for the person running JParty on the host machine. It focuses on what the host sees, what each startup option does, how the game flows once play begins, how to correct scores, and how to handle image clues smoothly.

For the project overview, setup, and development notes, see [README.md](README.md).
For the saved-state and clue-history file format, see
[docs/game-logging.md](docs/game-logging.md).

## Table of Contents

- [Before You Start](#before-you-start)
- [Welcome Screen Overview](#welcome-screen-overview)
- [Pre-Game Image Preview](#pre-game-image-preview)
- [Resume Flow](#resume-flow)
- [Core Game Flow](#core-game-flow)
- [Editing Scores](#editing-scores)
- [Image Selection and Approval During Play](#image-selection-and-approval-during-play)
- [General Host Advice](#general-host-advice)
- [Quick Reference](#quick-reference)

## Before You Start

- Use the host machine on the main display you will control during the game.
- Put the audience board on the TV or shared screen if you are using a two-screen setup.
- Make sure players are on the same network as the host machine so they can join from the QR code.
- Three players is the closest to a traditional Jeopardy! game, but JParty supports more or less if you want a bigger party game.

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
- Choose how many Final Jeopardy boards to include
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

For Daily Doubles, the dialog also exposes the wagered clue value so you can fix an incorrect wager amount.

Saving these changes rewrites the affected clue history and recalculates downstream scores, which is much better than manually patching a total when the real problem was an earlier ruling.

The `Edit Score` button is disabled when:

- A clue is currently active
- JParty is waiting for Daily Double player selection
- There is no recent clue history yet

### Clicking a player's podium

When no clue is active, clicking a player's podium opens a manual score override flow for that player.

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
- `Edit Score`: fix recent clue rulings
- Click podium with no active clue: manual score override
- `Load Question Media`: import clue images for a game id
- `Load Saved`: resume an earlier session
- `Advanced Options`: build a mixed-source custom game
