import argparse
import csv
from collections import defaultdict
from itertools import combinations


CARD_PREFIXES = (
    "opening_hand_",
    "drawn_",
    "tutored_",
)

EXCLUDED_CARDS = {
    "Forest",
    "Island",
    "Swamp",
    "Plains",
    "Mountain",
}


def calculate_card_pair_win_rates(
    input_csv: str,
    output_csv: str,
    min_cooccurrences: int = 20,
):
    """
    Calculate individual and pair game-in-hand win rates.

    A card is considered present if its count is > 0 in any of:
        opening_hand_<card name>
        drawn_<card name>
        tutored_<card name>

    Output columns:
        card_name_1
        card_name_2
        win_rate
        game_count

    Individual card statistics:
        card_name_1 == card_name_2

        Each game containing the card is counted exactly once.

    Pair statistics:
        card_name_1 != card_name_2

        Each game containing both cards is counted exactly once.

        Both symmetric pairs (A, B) and (B, A) are included.

    Minimum co-occurrences:
        Applies to both individual card statistics and card pairs.

    Memory usage:
        O(number of unique cards + number of unique card pairs).

    The input CSV is processed one row at a time.
    """

    # Individual card statistics:
    # card_name -> [game_count, win_count]
    card_stats = defaultdict(lambda: [0, 0])

    # Pair statistics:
    # (card_1, card_2) -> [game_count, win_count]
    pair_stats = defaultdict(lambda: [0, 0])

    with open(
        input_csv,
        "r",
        newline="",
        encoding="utf-8",
    ) as f:

        reader = csv.reader(f)

        header = next(reader)

        # Map each column index to its card name.
        card_columns = []

        for index, column_name in enumerate(header):

            for prefix in CARD_PREFIXES:

                if column_name.startswith(prefix):

                    card_name = column_name[len(prefix):]

                    if card_name not in EXCLUDED_CARDS:
                        card_columns.append(
                            (index, card_name)
                        )

                    break

        won_index = header.index("won")

        # Process the CSV one game at a time.
        for row in reader:

            # Find all distinct cards present in this game.
            present_cards = set()

            for column_index, card_name in card_columns:

                value = row[column_index]

                if value and float(value) > 0:
                    present_cards.add(card_name)

            if not present_cards:
                continue

            # Handle Boolean strings and numeric win indicators.
            won_value = row[won_index].strip().lower()

            if won_value in ("true", "1"):
                won = 1

            elif won_value in ("false", "0"):
                won = 0

            else:
                raise ValueError(
                    f"Unexpected value in won column: "
                    f"{row[won_index]!r}"
                )

            # ------------------------------------------------
            # Individual card statistics
            # ------------------------------------------------

            for card_name in present_cards:

                stats = card_stats[card_name]

                stats[0] += 1
                stats[1] += won

            # ------------------------------------------------
            # Pair statistics
            # ------------------------------------------------

            # Sort to ensure that each unordered pair
            # is counted exactly once per game.
            for card_1, card_2 in combinations(
                sorted(present_cards),
                2,
            ):

                stats = pair_stats[(card_1, card_2)]

                stats[0] += 1
                stats[1] += won

    # --------------------------------------------------------
    # Write output
    # --------------------------------------------------------

    with open(
        output_csv,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.writer(f)

        writer.writerow([
            "card_name_1",
            "card_name_2",
            "win_rate",
            "game_count",
        ])

        # ----------------------------------------------------
        # Individual card win rates
        # ----------------------------------------------------

        for card_name, (game_count, win_count) in card_stats.items():

            if game_count < min_cooccurrences:
                continue

            win_rate = win_count / game_count

            writer.writerow([
                card_name,
                card_name,
                win_rate,
                game_count,
            ])

        # ----------------------------------------------------
        # Pair win rates
        # ----------------------------------------------------

        for (
            card_1,
            card_2,
        ), (
            game_count,
            win_count,
        ) in pair_stats.items():

            if game_count < min_cooccurrences:
                continue

            win_rate = win_count / game_count

            # Include both symmetric pairs.
            writer.writerow([
                card_1,
                card_2,
                win_rate,
                game_count,
            ])

            writer.writerow([
                card_2,
                card_1,
                win_rate,
                game_count,
            ])


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Calculate individual and pair "
            "game-in-hand win rates."
        )
    )

    parser.add_argument(
        "input_csv",
        help="Path to the input CSV.",
    )

    parser.add_argument(
        "output_csv",
        help="Path to the output CSV.",
    )

    parser.add_argument(
        "--min-cooccurrences",
        type=int,
        default=20,
        help=(
            "Minimum number of games required for "
            "individual cards and card pairs (default: 20)."
        ),
    )

    args = parser.parse_args()

    calculate_card_pair_win_rates(
        input_csv=args.input_csv,
        output_csv=args.output_csv,
        min_cooccurrences=args.min_cooccurrences,
    )


if __name__ == "__main__":
    main()