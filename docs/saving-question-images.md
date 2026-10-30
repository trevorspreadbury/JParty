# Saving Question Images

This guide explains how to find image-based clues for a JParty game and save
them in the right place so JParty can load them automatically.

For the host-side flow for importing, previewing, and approving clue images,
see [HOST.md](../HOST.md).

## Overview

JParty can show local images for clues before the game starts or during play.
To make that work, you save image files under the game id using JParty's clue
numbering scheme.

The general workflow is:

1. Find the J-Archive game id you want to play.
2. Open that game on J-Archive.
3. Look through the boards for clues with hyperlinks.
4. Decide whether each linked clue really needs an image in JParty.
5. Find and save a matching image.
6. Name the file with the correct board/category/row numbering.

## Step 1: Get the game id

Open the game on J-Archive. The game id is the numeric id in the URL.

Example:

```text
https://j-archive.com/showgame.php?game_id=4453
```

The game id is:

```text
4453
```

Use that id as the folder name for the saved question images.

## Step 2: Look for clues with hyperlinks

On J-Archive, open the game page and scan the Jeopardy and Double Jeopardy
boards. Clues that link out to media are the main candidates for local images.

Not every hyperlink needs an image in JParty. Use judgment:

- If the clue obviously depends on seeing a person, place, object, artwork, or
  screenshot, save an image.
- If the hyperlink is incidental or the clue still works fine as plain text, you
  can skip it.

## Step 3: Find an image that fits the clue

For each clue that needs an image:

- find an image that matches what contestants should see
- prefer a clear, stable image without extra distracting overlays
- ensure the answer text does not appear in the image
- landscape images are preferred, but either is fine
- save a common image format such as `.png`, `.jpg`, `.jpeg`, or `.webp`

It is okay to save only the clues that truly need images. You do not need to
save images for every hyperlink in the game.

## Step 4: Name the image correctly

JParty expects the filename format:

```text
<board>-<category>-<row>.<extension>
```

Examples:

```text
0-0-0.png
0-3-2.jpg
1-5-4.webp
```

Where:

- `board`
  - `0` = Jeopardy
  - `1` = Double Jeopardy
  - `2` = Triple Jeopardy
- `category`
  - zero-based column index from left to right
- `row`
  - zero-based clue row from top to bottom

Use this visual guide:

![Question media numbering guide](../resources/question-media-labelling.png)

That image shows how clue positions map to the filename coordinates.

## Step 5: Save images in the game-id folder

If you are not hosting, zip each game and share it with the host. For the host, place the files in the folder for that game id under JParty's `question_media` directory.

Example layout:

```text
question_media/
  4453/
    0-0-0.png
    0-4-1.jpg
    1-2-3.png
```

If you are using repo-local development data with `DATA_DIR=.jparty-data`, that
usually means:

```text
.jparty-data/question_media/4453/
```

## Step 6 (host only): Load the images in JParty

On the welcome screen:

1. Enter the game id. If the folder/zip has already been moved to the question media directory, you should see a message that it was found.
2. If the media was not found or has not been moved, click `Load Question Media`. and choose the folder or zip file containing the numbered images.
3. After import, the summary should report that question media was found.
4. On game start, you should see the images matched up with their answers. 

If you want the full host walkthrough for that startup flow, see
[HOST.md](../HOST.md).
