"""MTG Build-Around Explorer.

Repository layout for Streamlit Community Cloud:

    .
    ├── app.py
    ├── requirements.txt
    └── data/
        ├── SOS_card_pairs.csv
        ├── EOE_card_pairs.csv
        └── ...

Every CSV in data/ must contain:
    card_name_1, card_name_2, win_rate, game_count

Rows with card_name_1 == card_name_2 contain individual-card GIH stats.
Other rows contain ordered pair statistics.
"""

import argparse
import math
from pathlib import Path

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode


st.set_page_config(
    page_title="MTG Build-Around Explorer",
    page_icon="🃏",
    layout="wide",
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
REQUIRED_COLUMNS = {"card_name_1", "card_name_2", "win_rate", "game_count"}


def discover_datasets(data_dir: Path) -> list[Path]:
    """Return all CSV datasets in data_dir, sorted by filename."""
    if not data_dir.exists():
        return []
    return sorted(
        (p for p in data_dir.glob("*.csv") if p.is_file()),
        key=lambda p: p.name.lower(),
    )


def dataset_label(path: Path) -> str:
    """Convert a CSV filename into a readable selector label."""
    label = path.stem
    for suffix in ("_card_pair_win_rates", "_card_pairs", "_car_pairs"):
        if label.lower().endswith(suffix):
            label = label[: -len(suffix)]
            break
    return label.replace("_", " ").replace("-", " ").strip() or path.stem


@st.cache_data(show_spinner="Loading card data…")
def load_data(
    csv_path: str,
    file_mtime_ns: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load one generated card-pair CSV.

    file_mtime_ns is part of the cache key so replacing a CSV locally
    invalidates the cached result even when the filename is unchanged.
    """
    del file_mtime_ns

    data = pd.read_csv(
        csv_path,
        usecols=lambda col: col in REQUIRED_COLUMNS,
        dtype={
            "card_name_1": "string",
            "card_name_2": "string",
            "win_rate": "float64",
            "game_count": "int64",
        },
    )

    missing = REQUIRED_COLUMNS - set(data.columns)
    if missing:
        raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")

    data = data.dropna(subset=list(REQUIRED_COLUMNS))
    data = data.loc[
        data["game_count"].gt(0) & data["win_rate"].between(0, 1)
    ].copy()

    diagonal = data.loc[data["card_name_1"].eq(data["card_name_2"])].copy()
    if diagonal["card_name_1"].duplicated().any():
        raise ValueError(
            "Found duplicate individual-card rows "
            "(card_name_1 == card_name_2)."
        )

    individual = diagonal.rename(
        columns={
            "card_name_1": "card",
            "win_rate": "individual_wr",
            "game_count": "games",
        }
    )[["card", "individual_wr", "games"]]

    pairs = data.loc[data["card_name_1"].ne(data["card_name_2"])].copy()
    if pairs.duplicated(["card_name_1", "card_name_2"]).any():
        raise ValueError("Found duplicate ordered card pairs in the CSV.")

    return individual, pairs


@st.cache_data(show_spinner="Calculating build-around statistics…")
def calculate_statistics(
    individual: pd.DataFrame,
    pairs: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate card-level build-around stats and enriched pair stats."""
    own = individual[["card", "individual_wr"]].rename(
        columns={"card": "card_name_1", "individual_wr": "wr_1"}
    )
    other = individual[["card", "individual_wr"]].rename(
        columns={"card": "card_name_2", "individual_wr": "wr_2"}
    )

    enriched = pairs.merge(
        own, on="card_name_1", how="left", validate="many_to_one"
    )
    enriched = enriched.merge(
        other, on="card_name_2", how="left", validate="many_to_one"
    )
    enriched = enriched.dropna(subset=["wr_1", "wr_2"]).copy()

    enriched["improvement"] = enriched["win_rate"] - enriched["wr_1"]
    enriched["synergy"] = (
        enriched["win_rate"] - enriched[["wr_1", "wr_2"]].max(axis=1)
    )

    def summarize(group: pd.DataFrame) -> pd.Series:
        # Every eligible pairing is weighted equally.
        best_n = max(1, math.ceil(len(group) * 0.10))
        best_row = group.sort_values(
            ["synergy", "card_name_2"], ascending=[False, True]
        ).iloc[0]
        return pd.Series(
            {
                "variance": group["win_rate"].var(ddof=0),
                "build_around": group["synergy"].nlargest(best_n).mean(),
                "pair_count": len(group),
                "best_partner": best_row["card_name_2"],
            }
        )

    if enriched.empty:
        summaries = pd.DataFrame(
            columns=[
                "card_name_1",
                "variance",
                "build_around",
                "pair_count",
                "best_partner",
            ]
        )
    else:
        summaries = (
            enriched.groupby("card_name_1", sort=False)
            .apply(summarize, include_groups=False)
            .reset_index()
        )

    summary = individual.merge(
        summaries,
        left_on="card",
        right_on="card_name_1",
        how="left",
    ).drop(columns="card_name_1")

    summary["pair_count"] = summary["pair_count"].fillna(0).astype(int)
    summary = summary.sort_values(
        ["build_around", "card"],
        ascending=[False, True],
        na_position="last",
    ).reset_index(drop=True)

    return summary, enriched


# Keep card art OUT of React rendering. Returning an HTMLElement from a
# cellRenderer can trigger React error #31 in streamlit-aggrid. These callbacks
# leave the grid cell as plain text and create a temporary overlay in the grid
# iframe's document.body instead.
SHOW_CARD_PREVIEW = JsCode(r"""
function(params) {
    const hoverFields = ['Card', 'Best Partner', 'Paired Card'];
    const field = params.column ? params.column.getColId() : null;
    if (!hoverFields.includes(field)) return;

    const name = params.value;
    if (typeof name !== 'string' || !name.trim()) return;

    function clearPreview() {
        if (window.mtgCardPreviewTimer) {
            clearTimeout(window.mtgCardPreviewTimer);
            window.mtgCardPreviewTimer = null;
        }
        if (window.mtgCardPreview) {
            window.mtgCardPreview.remove();
            window.mtgCardPreview = null;
        }
    }

    clearPreview();

    const mouseX = params.event ? params.event.clientX : 0;
    const mouseY = params.event ? params.event.clientY : 0;

    window.mtgCardPreviewTimer = setTimeout(function() {
        window.mtgCardPreviewTimer = null;

        const popup = document.createElement('div');
        popup.setAttribute('role', 'tooltip');
        popup.setAttribute('aria-label', name + ' card image');
        popup.style.position = 'fixed';
        popup.style.zIndex = '2147483647';
        popup.style.pointerEvents = 'none';
        popup.style.width = '250px';
        popup.style.padding = '5px';
        popup.style.borderRadius = '11px';
        popup.style.background = '#20242a';
        popup.style.boxShadow = '0 6px 24px rgba(0,0,0,0.55)';

        const image = document.createElement('img');
        image.alt = name;
        image.style.display = 'block';
        image.style.width = '100%';
        image.style.height = 'auto';
        image.style.borderRadius = '8px';
        image.src = 'https://api.scryfall.com/cards/named' +
            '?format=image&version=normal&exact=' + encodeURIComponent(name);

        image.onerror = function() {
            popup.replaceChildren();
            const message = document.createElement('div');
            message.textContent = 'Card image unavailable: ' + name;
            message.style.color = 'white';
            message.style.padding = '8px';
            message.style.fontSize = '13px';
            popup.appendChild(message);
        };

        popup.appendChild(image);
        document.body.appendChild(popup);

        const popupWidth = 260;
        const popupHeight = 365;
        const margin = 8;
        let left = mouseX + 18;
        let top = mouseY + 12;

        if (left + popupWidth > window.innerWidth - margin) {
            left = mouseX - popupWidth - 18;
        }
        if (top + popupHeight > window.innerHeight - margin) {
            top = window.innerHeight - popupHeight - margin;
        }

        popup.style.left = Math.max(margin, left) + 'px';
        popup.style.top = Math.max(margin, top) + 'px';
        window.mtgCardPreview = popup;
    }, 250);
}
""")


HIDE_CARD_PREVIEW = JsCode(r"""
function(params) {
    if (window.mtgCardPreviewTimer) {
        clearTimeout(window.mtgCardPreviewTimer);
        window.mtgCardPreviewTimer = null;
    }
    if (window.mtgCardPreview) {
        window.mtgCardPreview.remove();
        window.mtgCardPreview = null;
    }
}
""")


def card_grid(
    data: pd.DataFrame,
    *,
    name_column: str,
    key: str,
    height: int,
    selectable: bool = False,
):
    """Render a sortable AG Grid with card-art hover previews."""
    builder = GridOptionsBuilder.from_dataframe(data)
    builder.configure_default_column(sortable=True, resizable=True, filter=True)

    hover_style = {
        "cursor": "help",
        "textDecoration": "underline dotted",
        "textUnderlineOffset": "3px",
    }

    builder.configure_column(
        name_column,
        cellStyle=hover_style,
        minWidth=210,
        flex=2,
    )

    if "Best Partner" in data.columns:
        builder.configure_column(
            "Best Partner",
            cellStyle=hover_style,
            minWidth=190,
            flex=2,
        )

    for field in ("Mean WR", "Pair WR", "Individual WR (Partner)"):
        if field in data.columns:
            builder.configure_column(
                field,
                valueFormatter=JsCode(
                    """
                    function(p) {
                        return p.value == null
                            ? ''
                            : Number(p.value).toFixed(2) + '%';
                    }
                    """
                ),
                minWidth=125,
            )

    for field in ("Build-Around Potential", "Synergy Score", "WR Improvement"):
        if field in data.columns:
            builder.configure_column(
                field,
                valueFormatter=JsCode(
                    """
                    function(p) {
                        if (p.value == null) return '';
                        const v = Number(p.value);
                        return (v > 0 ? '+' : '') + v.toFixed(2) + ' pp';
                    }
                    """
                ),
                minWidth=145,
            )

    if "Variance" in data.columns:
        builder.configure_column(
            "Variance",
            valueFormatter=JsCode(
                """
                function(p) {
                    return p.value == null
                        ? ''
                        : Number(p.value).toFixed(2);
                }
                """
            ),
            minWidth=105,
        )

    for field in ("Games", "Pairings"):
        if field in data.columns:
            builder.configure_column(
                field,
                valueFormatter=JsCode(
                    """
                    function(p) {
                        return p.value == null
                            ? ''
                            : Number(p.value).toLocaleString();
                    }
                    """
                ),
                minWidth=105,
            )

    if selectable:
        builder.configure_selection(selection_mode="single", use_checkbox=False)

    grid_options = builder.build()
    grid_options["rowHeight"] = 36
    grid_options["onCellMouseOver"] = SHOW_CARD_PREVIEW
    grid_options["onCellMouseOut"] = HIDE_CARD_PREVIEW
    grid_options["onBodyScroll"] = HIDE_CARD_PREVIEW
    grid_options["suppressCellFocus"] = True

    return AgGrid(
        data,
        gridOptions=grid_options,
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        update_on=["selectionChanged"] if selectable else [],
        height=height,
        theme="streamlit",
        key=key,
        fit_columns_on_grid_load=True,
    )


def selected_card_from_grid(result) -> str | None:
    """Extract the selected Card across streamlit-aggrid return shapes."""
    rows = getattr(result, "selected_rows", None)

    if rows is None:
        try:
            rows = result["selected_rows"]
        except (KeyError, TypeError):
            return None

    if isinstance(rows, pd.DataFrame):
        if rows.empty or "Card" not in rows.columns:
            return None
        return str(rows.iloc[0]["Card"])

    if isinstance(rows, list) and rows:
        row = rows[0]
        if isinstance(row, dict) and "Card" in row:
            return str(row["Card"])

    return None


def choose_dataset(data_dir: Path, explicit_csv: Path | None) -> Path:
    """Render the dataset selector and return the chosen CSV."""
    if explicit_csv is not None:
        if not explicit_csv.exists():
            st.error(f"CSV does not exist: {explicit_csv}")
            st.stop()
        return explicit_csv

    datasets = discover_datasets(data_dir)
    if not datasets:
        st.error(
            f"No CSV files found in `{data_dir}`.\n\n"
            "Create a `data/` directory next to app.py and place one or "
            "more generated card-pair CSVs in it."
        )
        st.stop()

    return st.sidebar.selectbox(
        "Set / dataset",
        options=datasets,
        index=0,
        format_func=dataset_label,
        help="Every CSV in the repository's data/ directory appears here.",
        disabled=len(datasets) == 1,
    )


def show_app(data_dir: Path, explicit_csv: Path | None = None) -> None:
    st.title("MTG Build-Around Explorer")
    st.caption(
        "Individual game-in-hand win rates, upper-tail synergy, "
        "and card-pair win rates"
    )

    with st.sidebar:
        st.header("Explore")
        selected_csv = choose_dataset(data_dir, explicit_csv)
        st.caption(f"Source: `{selected_csv.name}`")
        search = st.text_input("Find a card", placeholder="Type part of a name…")
        st.caption(
            "Hover over card names to see card art. Click a row in the "
            "first table to inspect its partners in a second table below the first one. Click column headings to sort."
        )
        st.divider()
        st.markdown("**Definitions**")
        st.caption(
            "Build-Around Potential = unweighted mean of the top 10% of "
            "synergy scores for a card's eligible pairings (rounding up)."
        )
        st.caption(
            "Synergy = pair WR − max(individual WR of card 1, "
            "individual WR of card 2)."
        )
        st.caption(
            "Variance = unweighted population variance of a card's pair "
            "win rates, in percentage-points squared."
        )
        st.caption(
            "These are observed associations, not proof that one card "
            "causes another to win more."
        )

    try:
        individual, pairs = load_data(
            str(selected_csv), selected_csv.stat().st_mtime_ns
        )
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        st.error(f"Could not load `{selected_csv.name}`: {exc}")
        st.stop()

    if individual.empty:
        st.error(
            "No individual-card rows found "
            "(card_name_1 == card_name_2)."
        )
        st.stop()

    summary, enriched = calculate_statistics(individual, pairs)

    view = summary.copy()
    if search:
        view = view.loc[
            view["card"].str.contains(search, case=False, regex=False, na=False)
        ]

    if view.empty:
        st.info("No cards match the search.")
        return

    st.subheader(f"Cards — {dataset_label(selected_csv)}")
    st.caption(
        "Click on a card (or row) to open a table below with all partners. "
        "Default sort: highest Build-Around Potential first. Mean WR is "
        "each card's actual individual GIH win rate, not an average over "
        "pairs. Games counts distinct games containing that card."
    )

    display = view.copy()
    display["individual_wr"] *= 100
    display["build_around"] *= 100
    display["variance"] *= 10000
    display = display.rename(
        columns={
            "card": "Card",
            "individual_wr": "Mean WR",
            "variance": "Variance",
            "build_around": "Build-Around Potential",
            "games": "Games",
            "pair_count": "Pairings",
            "best_partner": "Best Partner",
        }
    )[
        [
            "Card",
            "Mean WR",
            "Variance",
            "Build-Around Potential",
            "Games",
            "Pairings",
            "Best Partner",
        ]
    ].reset_index(drop=True)

    dataset_key = selected_csv.stem.replace(" ", "_")
    picked = card_grid(
        display,
        name_column="Card",
        key=f"card_selection_{dataset_key}",
        height=510,
        selectable=True,
    )

    st.caption(
        "Variance is expressed in percentage-points squared. Build-Around "
        "Potential is measured in percentage points (pp)."
    )

    selected_name = selected_card_from_grid(picked)
    if selected_name is None:
        st.info(
            "Select a card in the table above to inspect its pairings. "
            "Hover over a card name to see its art."
        )
        return

    selected_rows = view.loc[view["card"].eq(selected_name)]
    if selected_rows.empty:
        st.info("Select a card from the currently displayed rows.")
        return
    selected = selected_rows.iloc[0]

    st.divider()
    st.subheader(f"Pairings for {selected_name}")

    a, b, c = st.columns(3)
    a.metric("Individual GIH WR", f"{selected['individual_wr']:.2%}")
    b.metric(
        "Build-Around Potential",
        "N/A"
        if pd.isna(selected["build_around"])
        else f"{selected['build_around'] * 100:+.2f} pp",
    )
    c.metric("Unique Games", f"{int(selected['games']):,}")

    detail = enriched.loc[
        enriched["card_name_1"].eq(selected_name)
    ].copy()
    if detail.empty:
        st.info("No eligible pairings for this card.")
        return

    detail = detail.sort_values(
        ["synergy", "game_count"], ascending=[False, False]
    )
    detail["Synergy Score"] = detail["synergy"] * 100
    detail["Pair WR"] = detail["win_rate"] * 100
    detail["WR Improvement"] = detail["improvement"] * 100
    detail["Individual WR (Partner)"] = detail["wr_2"] * 100
    detail = detail.rename(
        columns={"card_name_2": "Paired Card", "game_count": "Games"}
    )

    st.caption(
        "Default sort: highest Synergy Score first. WR Improvement compares "
        "the pair to the selected card; Synergy Score compares it to the "
        "stronger individual card. Both are in percentage points."
    )

    card_grid(
        detail[
            [
                "Paired Card",
                "Synergy Score",
                "Pair WR",
                "WR Improvement",
                "Individual WR (Partner)",
                "Games",
            ]
        ].reset_index(drop=True),
        name_column="Paired Card",
        key=f"pair_grid_{dataset_key}_{selected_name}",
        height=620,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Streamlit MTG build-around explorer"
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Directory containing card-pair CSV files (default: ./data)",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help=(
            "Optional single CSV override. If omitted, the app shows a "
            "selector for every CSV in --data-dir."
        ),
    )
    arguments, _ = parser.parse_known_args()

    show_app(
        data_dir=Path(arguments.data_dir).expanduser().resolve(),
        explicit_csv=(
            Path(arguments.csv).expanduser().resolve() if arguments.csv else None
        ),
    )
