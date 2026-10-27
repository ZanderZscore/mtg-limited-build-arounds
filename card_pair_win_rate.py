import argparse
import csv
import json
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import requests


CARD_PREFIXES = (
    "opening_hand_",
    "drawn_",
    "tutored_",
)

COLOR_ORDER = "WUBRG"

SCRYFALL_COLLECTION_URL = "https://api.scryfall.com/cards/collection"
SCRYFALL_BATCH_SIZE = 75
SCRYFALL_REQUEST_DELAY_SECONDS = 0.15

SCRYFALL_HEADERS = {
    "User-Agent": "MTGLimitedBuildAroundExplorer/1.0",
    "Accept": "application/json;q=0.9,*/*;q=0.8",
}


def parse_won(value: str) -> int:
    normalized = value.strip().lower()

    if normalized in {"true", "1"}:
        return 1
    if normalized in {"false", "0"}:
        return 0

    raise ValueError(f"Unexpected value in won column: {value!r}")


def normalize_color_context(value: str) -> str | None:
    """
    Canonicalize 17Lands main_colors.

    Examples:
        UW  -> WU
        WU  -> WU
        BUW -> WUB
        G   -> G
    """
    if value is None:
        return None

    text = str(value).strip().upper()
    if not text:
        return None

    present = {char for char in text if char in COLOR_ORDER}
    if not present:
        return None

    return "".join(
        char for char in COLOR_ORDER
        if char in present
    )


def load_scryfall_cache(cache_path: Path) -> dict[str, str]:
    if not cache_path.exists():
        return {}

    try:
        with cache_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    return {
        str(name): str(type_line)
        for name, type_line in data.items()
    }


def save_scryfall_cache(
    cache_path: Path,
    cache: dict[str, str],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(
            cache,
            f,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )


def batched(items, size):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def fetch_card_type_lines(
    card_names: set[str],
    cache_path: Path,
) -> dict[str, str]:
    """
    Resolve card names to Scryfall type lines and cache the results.
    """
    cache = load_scryfall_cache(cache_path)

    missing = sorted(
        name
        for name in card_names
        if name not in cache
    )

    if missing:
        print(
            f"Looking up {len(missing)} uncached card types "
            "from Scryfall..."
        )

    session = requests.Session()
    session.headers.update(SCRYFALL_HEADERS)

    unresolved = []

    for batch_number, batch in enumerate(
        batched(missing, SCRYFALL_BATCH_SIZE),
        start=1,
    ):
        payload = {
            "identifiers": [
                {"name": name}
                for name in batch
            ]
        }

        response = session.post(
            SCRYFALL_COLLECTION_URL,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

        result = response.json()

        returned_names = set()

        for card in result.get("data", []):
            requested_name = None
            card_name = card.get("name")

            if card_name in batch:
                requested_name = card_name

            if requested_name is None:
                candidate_names = {card_name}

                for face in card.get("card_faces") or []:
                    candidate_names.add(face.get("name"))

                for original_name in batch:
                    if original_name in candidate_names:
                        requested_name = original_name
                        break

            if requested_name is None:
                continue

            cache[requested_name] = card.get("type_line", "")
            returned_names.add(requested_name)

        for item in result.get("not_found", []):
            name = item.get("name")
            if name:
                unresolved.append(name)

        for name in batch:
            if name not in returned_names and name not in cache:
                unresolved.append(name)

        save_scryfall_cache(cache_path, cache)

        print(
            f"  Scryfall batch {batch_number}: "
            f"{len(returned_names)}/{len(batch)} resolved"
        )

        time.sleep(SCRYFALL_REQUEST_DELAY_SECONDS)

    if unresolved:
        unresolved = sorted(set(unresolved))
        print(
            f"WARNING: Could not resolve {len(unresolved)} card names. "
            "They will be kept rather than excluded."
        )

        for name in unresolved[:20]:
            print(f"  unresolved: {name}")

        if len(unresolved) > 20:
            print(f"  ... and {len(unresolved) - 20} more")

    return cache


def is_land(type_line: str) -> bool:
    """
    Exclude every card whose Scryfall type line contains Land.
    """
    if not type_line:
        return False

    tokens = (
        type_line.replace("—", " ")
        .replace("-", " ")
        .split()
    )

    return "Land" in tokens


def collect_card_columns(
    header: list[str],
    scryfall_cache_path: Path,
):
    candidate_columns = []
    card_names = set()

    for index, column_name in enumerate(header):
        for prefix in CARD_PREFIXES:
            if column_name.startswith(prefix):
                card_name = column_name[len(prefix):]
                candidate_columns.append((index, card_name))
                card_names.add(card_name)
                break

    type_lines = fetch_card_type_lines(
        card_names,
        scryfall_cache_path,
    )

    excluded_lands = {
        card_name
        for card_name in card_names
        if is_land(type_lines.get(card_name, ""))
    }

    print(
        f"Found {len(card_names)} unique cards; "
        f"excluding {len(excluded_lands)} lands."
    )

    return [
        (index, card_name)
        for index, card_name in candidate_columns
        if card_name not in excluded_lands
    ]


def calculate_card_pair_win_rates(
    input_csv: str,
    output_csv: str,
    min_cooccurrences: int = 20,
    scryfall_cache: str | None = None,
):
    """
    Calculate individual GIH win rates and color-context pair synergy.

    Every eligible (card A, card B, main_colors) context is reported
    separately.

    Adjusted Synergy(A,B | C)
        = WR(A,B | C)
          - max(WR(A | C), WR(B | C))

    The value is stored as a decimal:
        0.03 == +3 percentage points.

    Eligibility:
        * individual card must have at least min_cooccurrences globally
        * raw/global pair must have at least min_cooccurrences globally
        * pair must also have at least min_cooccurrences inside the
          specific color context

    Output includes symmetric ordered rows:
        (A, B, WU)
        (B, A, WU)

    If the same pair appears in WU and WUB with enough games, both
    contexts are written separately.
    """

    if min_cooccurrences < 1:
        raise ValueError("min_cooccurrences must be at least 1")

    cache_path = (
        Path(scryfall_cache).expanduser().resolve()
        if scryfall_cache
        else (
            Path(__file__).resolve().parent
            / ".scryfall_card_types.json"
        )
    )

    card_stats = defaultdict(lambda: [0, 0])
    pair_stats = defaultdict(lambda: [0, 0])

    card_context_stats = defaultdict(lambda: [0, 0])
    pair_context_stats = defaultdict(lambda: [0, 0])

    with open(
        input_csv,
        "r",
        newline="",
        encoding="utf-8",
    ) as f:
        reader = csv.reader(f)
        header = next(reader)

        try:
            won_index = header.index("won")
        except ValueError as exc:
            raise ValueError(
                "Input CSV is missing required column 'won'"
            ) from exc

        try:
            main_colors_index = header.index("main_colors")
        except ValueError as exc:
            raise ValueError(
                "Input CSV is missing required column 'main_colors'."
            ) from exc

        card_columns = collect_card_columns(
            header,
            cache_path,
        )

        for row_number, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise ValueError(
                    f"Row {row_number} has {len(row)} columns; "
                    f"expected {len(header)}."
                )

            won = parse_won(row[won_index])
            context = normalize_color_context(
                row[main_colors_index]
            )

            present_cards = set()

            for column_index, card_name in card_columns:
                value = row[column_index]

                if not value:
                    continue

                try:
                    present = float(value) > 0
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid card count at row {row_number}, "
                        f"column {header[column_index]!r}: {value!r}"
                    ) from exc

                if present:
                    present_cards.add(card_name)

            if not present_cards:
                continue

            for card_name in present_cards:
                stats = card_stats[card_name]
                stats[0] += 1
                stats[1] += won

            sorted_cards = sorted(present_cards)

            for card_1, card_2 in combinations(sorted_cards, 2):
                stats = pair_stats[(card_1, card_2)]
                stats[0] += 1
                stats[1] += won

            if context is None:
                continue

            for card_name in present_cards:
                stats = card_context_stats[(context, card_name)]
                stats[0] += 1
                stats[1] += won

            for card_1, card_2 in combinations(sorted_cards, 2):
                stats = pair_context_stats[
                    (context, card_1, card_2)
                ]
                stats[0] += 1
                stats[1] += won

    fieldnames = [
        "card_name_1",
        "card_name_2",
        "win_rate",
        "game_count",
        "color_context",
        "context_pair_win_rate",
        "context_pair_game_count",
        "card_1_context_win_rate",
        "card_1_context_game_count",
        "card_2_context_win_rate",
        "card_2_context_game_count",
        "stronger_context_card_win_rate",
        "adjusted_synergy",
    ]

    with open(
        output_csv,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )
        writer.writeheader()

        # Diagonal rows: global individual GIH statistics.
        for card_name in sorted(card_stats):
            game_count, win_count = card_stats[card_name]

            if game_count < min_cooccurrences:
                continue

            writer.writerow(
                {
                    "card_name_1": card_name,
                    "card_name_2": card_name,
                    "win_rate": win_count / game_count,
                    "game_count": game_count,
                }
            )

        # One output row per eligible pair/context.
        for (
            context,
            card_1,
            card_2,
        ), (
            context_pair_games,
            context_pair_wins,
        ) in sorted(pair_context_stats.items()):

            if context_pair_games < min_cooccurrences:
                continue

            global_pair_games, global_pair_wins = pair_stats[
                (card_1, card_2)
            ]

            if global_pair_games < min_cooccurrences:
                continue

            (
                card_1_context_games,
                card_1_context_wins,
            ) = card_context_stats[(context, card_1)]

            (
                card_2_context_games,
                card_2_context_wins,
            ) = card_context_stats[(context, card_2)]

            context_pair_wr = (
                context_pair_wins / context_pair_games
            )

            card_1_context_wr = (
                card_1_context_wins / card_1_context_games
            )

            card_2_context_wr = (
                card_2_context_wins / card_2_context_games
            )

            stronger_context_card_wr = max(
                card_1_context_wr,
                card_2_context_wr,
            )

            adjusted_synergy = (
                context_pair_wr
                - stronger_context_card_wr
            )

            global_pair_wr = (
                global_pair_wins / global_pair_games
            )

            common = {
                "win_rate": global_pair_wr,
                "game_count": global_pair_games,
                "color_context": context,
                "context_pair_win_rate": context_pair_wr,
                "context_pair_game_count": context_pair_games,
                "stronger_context_card_win_rate": (
                    stronger_context_card_wr
                ),
                "adjusted_synergy": adjusted_synergy,
            }

            writer.writerow(
                {
                    "card_name_1": card_1,
                    "card_name_2": card_2,
                    **common,
                    "card_1_context_win_rate": card_1_context_wr,
                    "card_1_context_game_count": card_1_context_games,
                    "card_2_context_win_rate": card_2_context_wr,
                    "card_2_context_game_count": card_2_context_games,
                }
            )

            writer.writerow(
                {
                    "card_name_1": card_2,
                    "card_name_2": card_1,
                    **common,
                    "card_1_context_win_rate": card_2_context_wr,
                    "card_1_context_game_count": card_2_context_games,
                    "card_2_context_win_rate": card_1_context_wr,
                    "card_2_context_game_count": card_1_context_games,
                }
            )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Calculate individual GIH WR and per-main_colors "
            "adjusted pair synergy from 17Lands Game Data."
        )
    )

    parser.add_argument(
        "input_csv",
        help="17Lands Game Data CSV",
    )

    parser.add_argument(
        "output_csv",
        help="Output card-pair CSV",
    )

    parser.add_argument(
        "--min-cooccurrences",
        type=int,
        default=20,
        help=(
            "Minimum games required globally and within each "
            "pair/color context (default: 20)."
        ),
    )

    parser.add_argument(
        "--scryfall-cache",
        default=None,
        help=(
            "Optional path to Scryfall type-line cache. "
            "Default: .scryfall_card_types.json next to script."
        ),
    )

    args = parser.parse_args()

    calculate_card_pair_win_rates(
        input_csv=args.input_csv,
        output_csv=args.output_csv,
        min_cooccurrences=args.min_cooccurrences,
        scryfall_cache=args.scryfall_cache,
    )


if __name__ == "__main__":
    main()
