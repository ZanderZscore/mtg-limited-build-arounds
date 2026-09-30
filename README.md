# MTG Limited Build-Around Explorer

An interactive Streamlit application for exploring card performance, card-pair synergy, and potential build-around cards using public **17Lands Game Data**.

The application identifies cards whose performance improves substantially when they appear alongside particular other cards.

A demo is availible at https://mtg-limited-build-arounds.streamlit.app/

Data is generated from the public datasets available from:
https://www.17lands.com/public_datasets

Use the **Game Data** datasets.

---

## Features

The project has two main components:

1. `card_pair_win_rate.py`
   - Processes raw 17Lands Game Data.
   - Calculates individual card game-in-hand win rates.
   - Calculates pair game-in-hand win rates.
   - Records the number of games for each card and pair.
   - Supports a configurable minimum number of co-occurrences.
   - Excludes basic lands.

2. `card_data_app.py`
   - Interactive Streamlit dashboard.
   - Supports multiple sets/datasets.
   - Calculates card-pair synergy.
   - Calculates Build-Around Potential.
   - Displays individual card win rates and pair statistics.
   - Allows interactive sorting and card selection.
   - Displays card images from Scryfall when hovering over card names.

---

# Data Source

Download Game Data CSV files from:

https://www.17lands.com/public_datasets

For example:

```text
game_data_public.Cube_-_Powered.PremierDraft.csv
```

The processing script considers a card to have been "in hand" during a game if it appears in any of these columns:

```text
opening_hand_<card name>
drawn_<card name>
tutored_<card name>
```

A card is considered present if its value in at least one of those columns is greater than zero.

The following basic lands are excluded:

```text
Forest
Island
Swamp
Plains
Mountain
```

---

# Installation

Python 3.11 is recommended.

Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

---

# Project Structure

A typical project directory looks like:

```text
mtg-limited-build-arounds/
├── card_data_app.py
├── card_pair_win_rate.py
├── requirements.txt
├── README.md
├── .gitignore
└── data/
    ├── SOS.csv
    ├── EOE.csv
    ├── DFT.csv
    └── CUBE(NOV_2025).csv
```

Every CSV inside `data/` is automatically discovered by the Streamlit application and becomes available in the dataset selector.

---

# Generating Card-Pair Data

Run `card_pair_win_rate.py` against a downloaded 17Lands Game Data CSV.

Example:

```bash
python card_pair_win_rate.py \
  ../../mtg_data/game_data_public.Cube_-_Powered.PremierDraft.csv \
  "data/CUBE(NOV_2025).csv" \
  --min-cooccurrences 500
```

The output filename is quoted because shells such as `zsh` interpret parentheses specially.

For example, this may fail:

```bash
data/CUBE(NOV_2025).csv
```

while this works:

```bash
"data/CUBE(NOV_2025).csv"
```

## Minimum co-occurrences

The `--min-cooccurrences` option determines how many games two cards must appear together in before their pair win rate is included.

For example:

```bash
--min-cooccurrences 500
```

means a card pair must occur in at least 500 games.

A higher threshold gives fewer but more heavily observed card pairs.

---

# Generated CSV Format

Each generated dataset has four columns:

```text
card_name_1,card_name_2,win_rate,game_count
```

Example:

```text
card_name_1,card_name_2,win_rate,game_count
Lightning Bolt,Lightning Bolt,0.6124,18432
Lightning Bolt,Counterspell,0.6531,1245
Counterspell,Lightning Bolt,0.6531,1245
```

## Individual card rows

When:

```text
card_name_1 == card_name_2
```

the row represents the card's individual Game-in-Hand Win Rate.

For example:

```text
Lightning Bolt,Lightning Bolt,0.6124,18432
```

means Lightning Bolt appeared in 18,432 games and those games had a 61.24% win rate.

Each game is counted once for the individual card statistic.

## Pair rows

When:

```text
card_name_1 != card_name_2
```

the row represents games in which both cards appeared.

For example:

```text
Lightning Bolt,Counterspell,0.6531,1245
```

means games containing both cards had a 65.31% win rate across 1,245 games.

Both symmetric pairings are written:

```text
Lightning Bolt,Counterspell,...
Counterspell,Lightning Bolt,...
```

This allows statistics to be calculated from the perspective of either card.

---

# Running the Dashboard

Once one or more processed CSV files are present in `data/`, start the application with:

```bash
streamlit run card_data_app.py
```

The application automatically finds all:

```text
data/*.csv
```

files.

Use the **Set / dataset** selector in the sidebar to switch between datasets.

No code changes are required when adding another set.

Simply generate another CSV and place it in `data/`.

---

# Dashboard Statistics

## Individual GIH Win Rate

The Individual Game-in-Hand Win Rate is:

```text
games won when the card appeared
--------------------------------
games in which the card appeared
```

A card counts as appearing if it was:

- in the opening hand,
- drawn, or
- tutored.

Each game is counted once.

---

## Pair Win Rate

The Pair Win Rate measures the win rate when both cards appeared in the same game.

For cards A and B:

```text
WR(A, B)
```

is:

```text
games won containing both A and B
---------------------------------
games containing both A and B
```

---

## Win Rate Improvement

Win Rate Improvement is calculated from the perspective of the selected card.

For selected card A and partner B:

```text
WR Improvement(A, B) = WR(A, B) - WR(A)
```

For example:

```text
Individual WR of A = 52%
Pair WR of A + B   = 63%

WR Improvement = +11 percentage points
```

This statistic is directional.

Therefore:

```text
Improvement(A, B)
```

does not necessarily equal:

```text
Improvement(B, A)
```

---

## Synergy Score

The Synergy Score compares the pair against the stronger individual card.

For cards A and B:

```text
Synergy(A, B) =
    WR(A, B) - max(WR(A), WR(B))
```

Example:

```text
Card A Individual WR = 52%
Card B Individual WR = 55%
Pair WR              = 66%

Synergy Score = 66% - 55%
              = +11 percentage points
```

A positive synergy score means the pair's observed win rate is higher than the individual win rate of either card.

The Synergy Score is symmetric:

```text
Synergy(A, B) = Synergy(B, A)
```

---

# Build-Around Potential

Build-Around Potential attempts to identify cards whose strongest pairings perform substantially better than either card individually.

For each card:

1. Calculate the Synergy Score with every eligible partner.
2. Find the highest Synergy Score.

Conceptually:

```text
Build-Around Potential(A)
    =
mean(top 1 of Synergy(A, B))
```

For example, suppose the top synergy scores for a card are:

```text
+14 pp
+12 pp
+10 pp
```

Then:

```text
Build-Around Potential
    = (14 + 12 + 10) / 3
    = +12 pp
```

A high Build-Around Potential indicates that the card has a subset of partners with substantially stronger observed results.

The statistic is intentionally **not weighted by game count**.

The minimum co-occurrence threshold applied during preprocessing is used to control which pairings are eligible.

---

# Variance

Variance measures how much a card's pair win rates vary across its eligible partners.

The application uses the unweighted population variance of pair win rates.

A higher variance means the card's observed performance changes substantially depending on what other card appears alongside it.

Variance and Build-Around Potential measure different properties:

- **Variance** measures how much pair results vary overall.
- **Build-Around Potential** focuses specifically on the strongest synergy outcomes.

---

# Main Card Table

The main table contains:

```text
Card
Mean WR
Variance
Build-Around Potential
Games
Pairings
Best Partner
```

### Mean WR

The card's actual individual Game-in-Hand Win Rate.

It is not the average of the card's pair win rates.

### Games

The number of unique games in which the card appeared.

### Pairings

The number of eligible partner cards in the processed dataset.

### Best Partner

The card with the highest Synergy Score with the given card.

### Build-Around Potential

The mean of the card's top 10% Synergy Scores.

The table is initially sorted by Build-Around Potential from highest to lowest.

Any column can be clicked to sort by that statistic instead.

---

# Pairing Table

Selecting a card in the main table opens a detailed pairing table.

The columns are:

```text
Paired Card
Synergy Score
Pair WR
WR Improvement
Individual WR (Partner)
Games
```

The table is initially sorted by:

```text
Synergy Score
```

from highest to lowest.

---

# Card Images

Hovering over a card name displays its card image.

Images are retrieved from Scryfall:

https://scryfall.com/

The application does not load every image when the page starts.

Instead, the browser requests the image only when the user hovers over a card name.

Hover previews are available for:

- Card
- Best Partner
- Paired Card

An internet connection is required for card images.

---

# Adding a New Set

Download another Game Data dataset from 17Lands.

For example:

```text
game_data_public.TLA.PremierDraft.csv
```

Process it:

```bash
python card_pair_win_rate.py \
  ../../mtg_data/game_data_public.TLA.PremierDraft.csv \
  data/TLA.csv \
  --min-cooccurrences 500
```

Now the directory might contain:

```text
data/
├── SOS.csv
├── TLA.csv
└── CUBE(NOV_2025).csv
```

Restart or refresh the Streamlit application.

The new dataset will automatically appear in the **Set / dataset** selector.

---

# Important Statistical Caveats

The dashboard is intended as an exploratory tool.

A high Synergy Score does not prove that two cards mechanically cause one another to perform better.

Observed pair win rates can also be influenced by:

- overall deck quality,
- archetype strength,
- player skill,
- card color combinations,
- draft position,
- game length,
- other cards in the deck,
- contextual correlations between cards.

For example, two cards may have a high Synergy Score because both commonly appear in a strong archetype rather than because they directly interact.

Build-Around Potential should therefore be interpreted as:

> Cards whose strongest observed pairings substantially outperform the cards' individual win rates.

It is useful for identifying combinations worth investigating, not establishing causal card interactions.

---

# Requirements

Install dependencies for streamlit with:

```bash
pip install -r requirements.txt
```

The Streamlit application uses:

```text
streamlit
pandas
streamlit-aggrid
```

The preprocessing script primarily uses Python's standard library and is designed to process large CSV files incrementally rather than loading the complete 17Lands Game Data file into memory.

---

# Typical Workflow

```text
17Lands Public Game Data
          │
          ▼
card_pair_win_rate.py
          │
          ▼
data/SET.csv
          │
          ▼
Streamlit Dashboard
          │
          ├── Individual GIH Win Rate
          ├── Build-Around Potential
          ├── Pair Win Rate
          ├── Synergy Score
          └── Card Image Previews
```

A typical command sequence is:

```bash
python card_pair_win_rate.py \
  ../../mtg_data/game_data_public.Cube_-_Powered.PremierDraft.csv \
  "data/CUBE(NOV_2025).csv" \
  --min-cooccurrences 500
```

followed by:

```bash
streamlit run card_data_app.py
```