# MTG Build-Around Explorer

Analyze Magic: The Gathering game-in-hand (GIH) win rates for individual cards and card pairs, then explore build-around potential and pair synergy in a Streamlit dashboard.

**Data source:** [17Lands Public Datasets](https://www.17lands.com/public_datasets). Download a CSV from the **Game Data** column for the set and event type you want to analyze. This project is an independent analysis of that data, not an official 17Lands application. Follow the dataset's published terms and attribution requirements.

## Requirements

- Python 3.11 or newer recommended.
- A 17Lands **Game Data** CSV containing `won` and card-count columns named `opening_hand_<card name>`, `drawn_<card name>`, and/or `tutored_<card name>`.
- Enough disk space for the downloaded data and the derived CSV. The source CSV may be large.

Install the app dependencies (the CSV-processing script itself uses only the Python standard library):

```bash
python -m pip install -r requirements.txt
```

## Files

```text
card_pair_win_rate.py   # Stream game data into per-card and per-pair win rates
app.py                  # Streamlit build-around and synergy dashboard
requirements.txt
README.md
```

The raw Game Data download and generated CSV are supplied separately.

## 1. Generate the statistics CSV

Download Game Data from 17Lands and run, replacing the paths with your files:

```bash
python card_pair_win_rate.py \
  /path/to/game_data.csv \
  card_pair_win_rates.csv \
  --min-cooccurrences 100
```

`--min-cooccurrences` defaults to **20**. It specifies the minimum number of games in which a *single card* or *pair of distinct cards* must occur for that row to appear in the output. The threshold is applied during CSV generation; the dashboard does not recover pairs excluded by this threshold. To include all observed pairings, use `--min-cooccurrences 1`.

The script reads the input **one game (CSV row) at a time** and holds only per-card and per-pair aggregate counts in memory; it does not load the full game dataset into a DataFrame. Runtime depends on the number of game rows, card columns, and cards present per game. Memory grows with the number of distinct observed cards and pairs, not the number of games.

A card is present in a game if any of its opening-hand, drawn, or tutored counts is greater than zero. It is counted only once in that game, even if found in several columns. `won` accepts `True`/`False` or `1`/`0`. The basic lands **Forest, Island, Swamp, Plains, and Mountain** are excluded; other lands are retained. Each input row is treated as one game. For a consistent comparison, process one set/event-type dataset at a time, or deliberately combine compatible data.

### Output CSV

The generated file has four columns:

```csv
card_name_1,card_name_2,win_rate,game_count
Card A,Card A,0.60,100
Card B,Card B,0.55,120
Card A,Card B,0.70,30
Card B,Card A,0.70,30
```

The example rows above are illustrative, not actual card results.

- **Same name twice** (`A,A`): individual GIH win rate and the number of distinct game rows containing A.
- **Different names** (`A,B`): win rate and number of game rows containing both cards; both ordered versions (`A,B` and `B,A`) are written.
- `win_rate` is a proportion from 0 to 1; the app displays percentages.
- `game_count` refers to unique games *within that row's card/card-pair condition*. Summing counts across pair rows does **not** give the distinct games for an individual card.

## 2. Launch the dashboard

```bash
streamlit run card_data_app.py -- --csv card_pair_win_rates.csv
```

The `--` passes the `--csv` option to the app rather than to Streamlit. You can also omit `--csv` if a file named `card_pairs.csv` is placed next to `card_data_app.py`, although passing the path explicitly is recommended.

The **Cards** table is initially sorted by Build-Around Potential, highest first. Click column headings to sort by other statistics, search by card name in the sidebar, and select a row to view its pairings. The **Pairings** table initially sorts by pair win rate, highest first; click the Synergy Score or WR Improvement heading to sort by those measures instead.

### Dashboard Statistics

The dashboard provides several statistics to help identify Magic: The Gathering cards that perform particularly well when paired with specific other cards. All statistics are calculated using game-in-hand data from 17Lands.

| Statistic                  | Description                                                                                                                                                                                                                                                                               |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Individual Win Rate**    | The percentage of games won when the card appeared in the player's opening hand, was drawn, or was tutored. Each game is counted once.                                                                                                                                                    |
| **Variance**               | The variance of the card's win rates across all eligible pairings. Each pairing is weighted equally, regardless of the number of games played. Higher variance indicates that the card's observed win rate changes more substantially depending on which other cards appear alongside it. |
| **Build-Around Potential** | The average of the highest 10% of synergy scores among the card's eligible pairings. Higher values indicate that the card has pairings whose observed win rates substantially exceed the individual win rates of both cards.                                                              |
| **Games**                  | The total number of games in which the card appeared in the player's opening hand, was drawn, or was tutored.                                                                                                                                                                             |
| **Pairings**               | The number of distinct cards with which the card has sufficient co-occurrences to be included in the analysis.                                                                                                                                                                            |
| **Best Partner**           | The card with the highest observed synergy score when paired with the selected card.                                                                                                                                                         

### How Build-Around Potential Is Calculated

For each pair of cards A and B, the synergy score is:

$$
S(A,B)=WR(A,B)-\max(WR(A),WR(B))
$$

For each card, all eligible pairings are ranked by synergy score. Build-Around Potential is calculated as the arithmetic mean of the highest 10% of those scores.

For example, if a card's top three synergy scores are +15, +12, and +9 percentage points, its Build-Around Potential is:

$$
BA(A)=\frac{15+12+9}{3}=\boxed{+12\text{ percentage points}}
$$

**Interpretation:** A high Build-Around Potential identifies a card whose strongest pairings have substantially higher observed win rates than either card achieves individually.
                                            |

### Card Pair Statistics

Selecting a card in the main table displays its individual pairings, sorted by synergy score from highest to lowest.

| Statistic                         | Description                                                                                                                                                                        |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Synergy Score**                 | The pair's win rate minus the higher individual win rate of the two cards. A positive score indicates that the pair's observed win rate exceeds both cards' individual win rates.  |
| **Pair Win Rate**                 | The percentage of games won when both cards appeared in the player's opening hand, were drawn, or were tutored.                                                                    |
| **Win Rate Improvement**          | The pair's win rate minus the selected card's individual win rate. This measures how much the selected card's observed win rate changes when it appears alongside the paired card. |
| **Individual Win Rate (Partner)** | The individual game-in-hand win rate of the paired card.                                                                                                                           |
| **Games**                         | The number of games in which both cards appeared.                                                                                                                                  |


### Important Statistical Considerations

These statistics describe observed associations rather than proving that particular cards cause each other to perform better. Differences in deck composition, archetype, player skill, and other factors can influence pair win rates.

Build-Around Potential and variance weight every eligible pairing equally, regardless of its game count. A minimum co-occurrence threshold can be applied when generating the input CSV to exclude pairings with insufficient observations.

A high synergy score is therefore a useful starting point for investigating promising card combinations, but it does not necessarily establish that the cards have a direct mechanical interaction or that including them together will improve a deck's win rate.

### Troubleshooting

- **`TypeError: 'str' object cannot be interpreted as an integer` from `st.dataframe(width='stretch')`:** use the included `app.py`, which uses `use_container_width=True` for compatibility with the supported Streamlit versions.
- **No pairing shown:** it may have fewer than the selected `--min-cooccurrences` games, or the card may have no eligible partners.
- **Slow initial load:** the game-level CSV is streamed by the processing script, but the derived pair CSV is loaded into memory by Streamlit. Repeated app runs benefit from Streamlit caching.
