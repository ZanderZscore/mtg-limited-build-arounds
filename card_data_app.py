"""MTG Build-Around Explorer with per-color-context adjusted synergy."""

import argparse
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

BASE_REQUIRED_COLUMNS = {
    "card_name_1",
    "card_name_2",
    "win_rate",
    "game_count",
}

ADJUSTED_REQUIRED_COLUMNS = {
    "color_context",
    "context_pair_win_rate",
    "context_pair_game_count",
    "card_1_context_win_rate",
    "card_1_context_game_count",
    "card_2_context_win_rate",
    "card_2_context_game_count",
    "stronger_context_card_win_rate",
    "adjusted_synergy",
}


def discover_datasets(data_dir: Path) -> list[Path]:
    if not data_dir.exists():
        return []

    return sorted(
        (
            path
            for path in data_dir.glob("*.csv")
            if path.is_file()
        ),
        key=lambda path: path.name.lower(),
    )


def dataset_label(path: Path) -> str:
    label = path.stem

    for suffix in (
        "_card_pair_win_rates",
        "_card_pairs",
        "_car_pairs",
    ):
        if label.lower().endswith(suffix):
            label = label[: -len(suffix)]
            break

    return (
        label.replace("_", " ")
        .replace("-", " ")
        .strip()
        or path.stem
    )


@st.cache_data(show_spinner="Loading card data…")
def load_data(
    csv_path: str,
    file_mtime_ns: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    del file_mtime_ns

    data = pd.read_csv(csv_path)

    missing_base = BASE_REQUIRED_COLUMNS - set(data.columns)
    if missing_base:
        raise ValueError(
            "CSV is missing required columns: "
            + ", ".join(sorted(missing_base))
        )

    missing_adjusted = ADJUSTED_REQUIRED_COLUMNS - set(data.columns)
    if missing_adjusted:
        raise ValueError(
            "This CSV was generated with an older preprocessing script. "
            "Re-run card_pair_win_rate.py. Missing: "
            + ", ".join(sorted(missing_adjusted))
        )

    numeric_columns = [
        "win_rate",
        "game_count",
        "context_pair_win_rate",
        "context_pair_game_count",
        "card_1_context_win_rate",
        "card_1_context_game_count",
        "card_2_context_win_rate",
        "card_2_context_game_count",
        "stronger_context_card_win_rate",
        "adjusted_synergy",
    ]

    for column in numeric_columns:
        data[column] = pd.to_numeric(
            data[column],
            errors="coerce",
        )

    data = data.dropna(
        subset=[
            "card_name_1",
            "card_name_2",
            "win_rate",
            "game_count",
        ]
    )

    data = data.loc[
        data["game_count"].gt(0)
        & data["win_rate"].between(0, 1)
    ].copy()

    diagonal = data.loc[
        data["card_name_1"].eq(data["card_name_2"])
    ].copy()

    if diagonal["card_name_1"].duplicated().any():
        raise ValueError(
            "Found duplicate individual-card rows."
        )

    individual = diagonal.rename(
        columns={
            "card_name_1": "card",
            "win_rate": "individual_wr",
            "game_count": "games",
        }
    )[["card", "individual_wr", "games"]]

    pairs = data.loc[
        data["card_name_1"].ne(data["card_name_2"])
    ].copy()

    # A pair can now legitimately appear multiple times, once per color context.
    if pairs.duplicated(
        ["card_name_1", "card_name_2", "color_context"]
    ).any():
        raise ValueError(
            "Found duplicate ordered card-pair/color-context rows."
        )

    return individual, pairs


def calculate_statistics(
    individual: pd.DataFrame,
    pairs: pd.DataFrame,
    min_adjusted_synergy: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    min_adjusted_synergy is a decimal:
        0.03 == +3 percentage points.

    Only pair/context rows at or above the threshold contribute to:
        * Build-Around Potential
        * Pairings count
        * Best Partner / Best Context
        * the detail table
    """
    global_1 = individual[
        ["card", "individual_wr"]
    ].rename(
        columns={
            "card": "card_name_1",
            "individual_wr": "wr_1_global",
        }
    )

    global_2 = individual[
        ["card", "individual_wr"]
    ].rename(
        columns={
            "card": "card_name_2",
            "individual_wr": "wr_2_global",
        }
    )

    enriched = pairs.merge(
        global_1,
        on="card_name_1",
        how="left",
        validate="many_to_one",
    )

    enriched = enriched.merge(
        global_2,
        on="card_name_2",
        how="left",
        validate="many_to_one",
    )

    enriched["raw_synergy"] = (
        enriched["win_rate"]
        - enriched[
            ["wr_1_global", "wr_2_global"]
        ].max(axis=1)
    )

    eligible = enriched.dropna(
        subset=["adjusted_synergy"]
    ).copy()

    eligible = eligible.loc[
        eligible["adjusted_synergy"]
        >= min_adjusted_synergy
    ].copy()

    def summarize(group: pd.DataFrame) -> pd.Series:
        best = group.sort_values(
            [
                "adjusted_synergy",
                "context_pair_game_count",
                "card_name_2",
                "color_context",
            ],
            ascending=[
                False,
                False,
                True,
                True,
            ],
        ).iloc[0]

        # Pairings counts pair/context rows, not unique partner names,
        # because the same partner may qualify in multiple contexts.
        return pd.Series(
            {
                "variance": group["adjusted_synergy"].var(ddof=0),
                "build_around": best["adjusted_synergy"],
                "pair_count": len(group),
                "unique_partner_count": group["card_name_2"].nunique(),
                "best_partner": best["card_name_2"],
                "best_context": best["color_context"],
            }
        )

    if eligible.empty:
        summaries = pd.DataFrame(
            columns=[
                "card_name_1",
                "variance",
                "build_around",
                "pair_count",
                "unique_partner_count",
                "best_partner",
                "best_context",
            ]
        )
    else:
        summaries = (
            eligible.groupby("card_name_1", sort=False)
            .apply(summarize, include_groups=False)
            .reset_index()
        )

    summary = individual.merge(
        summaries,
        left_on="card",
        right_on="card_name_1",
        how="left",
    ).drop(columns="card_name_1")

    summary["pair_count"] = (
        summary["pair_count"]
        .fillna(0)
        .astype(int)
    )

    summary["unique_partner_count"] = (
        summary["unique_partner_count"]
        .fillna(0)
        .astype(int)
    )

    summary = summary.sort_values(
        ["build_around", "card"],
        ascending=[False, True],
        na_position="last",
    ).reset_index(drop=True)

    return summary, eligible


SHOW_CARD_PREVIEW = JsCode(r"""
function(params) {
    const hoverFields = ['Card', 'Best Partner', 'Paired Card'];
    const field = params.column ? params.column.getColId() : null;

    if (!hoverFields.includes(field)) return;

    const name = params.value;
    if (typeof name !== 'string' || !name.trim()) return;

    if (window.mtgCardPreviewTimer) {
        clearTimeout(window.mtgCardPreviewTimer);
        window.mtgCardPreviewTimer = null;
    }

    if (window.mtgCardPreview) {
        window.mtgCardPreview.remove();
        window.mtgCardPreview = null;
    }

    const mouseX = params.event ? params.event.clientX : 0;
    const mouseY = params.event ? params.event.clientY : 0;

    window.mtgCardPreviewTimer = setTimeout(function() {
        window.mtgCardPreviewTimer = null;

        const popup = document.createElement('div');
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

        image.src =
            'https://api.scryfall.com/cards/named'
            + '?format=image&version=normal&exact='
            + encodeURIComponent(name);

        image.onerror = function() {
            popup.replaceChildren();
            const message = document.createElement('div');
            message.textContent = 'Card image unavailable: ' + name;
            message.style.color = 'white';
            message.style.padding = '8px';
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
    builder = GridOptionsBuilder.from_dataframe(data)

    builder.configure_default_column(
        sortable=True,
        resizable=True,
        filter=True,
    )

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

    percent_fields = (
        "Mean WR",
        "Pair WR",
        "Context Pair WR",
        "Card WR in Context",
        "Partner WR in Context",
        "Stronger Card WR in Context",
    )

    for field in percent_fields:
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
                minWidth=135,
            )

    pp_fields = (
        "Build-Around Potential",
        "Adjusted Synergy",
        "Raw Synergy",
    )

    for field in pp_fields:
        if field in data.columns:
            builder.configure_column(
                field,
                valueFormatter=JsCode(
                    """
                    function(p) {
                        if (p.value == null) return '';
                        const v = Number(p.value);
                        return (v > 0 ? '+' : '')
                            + v.toFixed(2) + ' pp';
                    }
                    """
                ),
                minWidth=150,
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

    for field in (
        "Games",
        "Pair Contexts",
        "Unique Partners",
        "Context Pair Games",
    ):
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
                minWidth=115,
            )

    if selectable:
        builder.configure_selection(
            selection_mode="single",
            use_checkbox=False,
        )

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


def choose_dataset(
    data_dir: Path,
    explicit_csv: Path | None,
) -> Path:
    if explicit_csv is not None:
        if not explicit_csv.exists():
            st.error(f"CSV does not exist: {explicit_csv}")
            st.stop()

        return explicit_csv

    datasets = discover_datasets(data_dir)

    if not datasets:
        st.error(
            f"No CSV files found in `{data_dir}`."
        )
        st.stop()

    return st.sidebar.selectbox(
        "Set / dataset",
        options=datasets,
        index=0,
        format_func=dataset_label,
        help="Every CSV in data/ appears here.",
        disabled=len(datasets) == 1,
    )


def show_app(
    data_dir: Path,
    explicit_csv: Path | None = None,
) -> None:
    st.title("MTG Build-Around Explorer")

    st.caption(
        "Individual GIH win rates and per-color-context "
        "card-pair synergy"
    )

    with st.sidebar:
        st.header("Explore")

        selected_csv = choose_dataset(
            data_dir,
            explicit_csv,
        )

        st.caption(f"Source: `{selected_csv.name}`")

        min_synergy_pp = st.number_input(
            "Minimum Adjusted Synergy (pp)",
            min_value=-50.0,
            max_value=50.0,
            value=3.0,
            step=0.5,
            help=(
                "Only pair/color-context rows at or above this "
                "Adjusted Synergy are shown and used in the "
                "Build-Around Potential ranking."
            ),
        )

        search = st.text_input(
            "Find a card",
            placeholder="Type part of a name…",
        )

        st.caption(
            "Hover over card names to see card art. "
            "Click a row to inspect its qualifying pair/context rows."
        )

        st.divider()
        st.markdown("**Definitions**")

        st.caption(
            "Adjusted Synergy = pair WR inside one main_colors "
            "context − the higher of the two cards' individual WRs "
            "inside that same context."
        )

        st.caption(
            "Each qualifying main_colors context is reported separately. "
            "The same partner can therefore appear more than once."
        )

        st.caption(
            "Build-Around Potential = the single highest Adjusted "
            "Synergy score among rows meeting the selected threshold."
        )

    try:
        individual, pairs = load_data(
            str(selected_csv),
            selected_csv.stat().st_mtime_ns,
        )
    except (
        OSError,
        ValueError,
        pd.errors.ParserError,
    ) as exc:
        st.error(
            f"Could not load `{selected_csv.name}`: {exc}"
        )
        st.stop()

    if individual.empty:
        st.error("No individual-card rows found.")
        st.stop()

    summary, eligible = calculate_statistics(
        individual,
        pairs,
        min_adjusted_synergy=min_synergy_pp / 100.0,
    )

    view = summary.copy()

    if search:
        view = view.loc[
            view["card"].str.contains(
                search,
                case=False,
                regex=False,
                na=False,
            )
        ]

    if view.empty:
        st.info("No cards match the search.")
        return

    st.subheader(
        f"Cards — {dataset_label(selected_csv)}"
    )

    st.caption(
        f"Only pair/context rows with Adjusted Synergy ≥ "
        f"{min_synergy_pp:.1f} pp contribute to this table."
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
            "pair_count": "Pair Contexts",
            "unique_partner_count": "Unique Partners",
            "best_partner": "Best Partner",
            "best_context": "Best Context",
        }
    )[
        [
            "Card",
            "Mean WR",
            "Build-Around Potential",
            "Variance",
            "Games",
            "Pair Contexts",
            "Unique Partners",
            "Best Partner",
            "Best Context",
        ]
    ].reset_index(drop=True)

    dataset_key = selected_csv.stem.replace(" ", "_")

    picked = card_grid(
        display,
        name_column="Card",
        key=(
            f"card_selection_{dataset_key}_"
            f"{min_synergy_pp:.2f}"
        ),
        height=510,
        selectable=True,
    )

    selected_name = selected_card_from_grid(picked)

    if selected_name is None:
        st.info(
            "Select a card above to inspect its qualifying pairings."
        )
        return

    selected_rows = view.loc[
        view["card"].eq(selected_name)
    ]

    if selected_rows.empty:
        st.info(
            "Select a card from the currently displayed rows."
        )
        return

    selected = selected_rows.iloc[0]

    st.divider()
    st.subheader(f"Pairings for {selected_name}")

    a, b, c = st.columns(3)

    a.metric(
        "Individual GIH WR",
        f"{selected['individual_wr']:.2%}",
    )

    b.metric(
        "Build-Around Potential",
        (
            "N/A"
            if pd.isna(selected["build_around"])
            else f"{selected['build_around'] * 100:+.2f} pp"
        ),
    )

    c.metric(
        "Unique Games",
        f"{int(selected['games']):,}",
    )

    detail = eligible.loc[
        eligible["card_name_1"].eq(selected_name)
    ].copy()

    if detail.empty:
        st.info(
            f"No pair/color-context rows for this card meet "
            f"the {min_synergy_pp:.1f} pp threshold."
        )
        return

    detail = detail.sort_values(
        [
            "adjusted_synergy",
            "context_pair_game_count",
            "card_name_2",
            "color_context",
        ],
        ascending=[
            False,
            False,
            True,
            True,
        ],
    )

    detail["Adjusted Synergy"] = (
        detail["adjusted_synergy"] * 100
    )

    detail["Raw Synergy"] = (
        detail["raw_synergy"] * 100
    )

    detail["Context Pair WR"] = (
        detail["context_pair_win_rate"] * 100
    )

    detail["Card WR in Context"] = (
        detail["card_1_context_win_rate"] * 100
    )

    detail["Partner WR in Context"] = (
        detail["card_2_context_win_rate"] * 100
    )

    detail = detail.rename(
        columns={
            "card_name_2": "Paired Card",
            "color_context": "Color Context",
            "context_pair_game_count": "Context Pair Games",
            "game_count": "Games",
        }
    )

    st.caption(
        "The same Paired Card can appear in multiple rows when it "
        "qualifies in multiple main_colors contexts."
    )

    card_grid(
        detail[
            [
                "Paired Card",
                "Adjusted Synergy",
                "Color Context",
                "Context Pair WR",
                "Card WR in Context",
                "Partner WR in Context",
                "Context Pair Games",
            ]
        ].reset_index(drop=True),
        name_column="Paired Card",
        key=(
            f"pair_grid_{dataset_key}_"
            f"{selected_name}_{min_synergy_pp:.2f}"
        ),
        height=650,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Streamlit MTG build-around explorer"
    )

    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
    )

    parser.add_argument(
        "--csv",
        default=None,
    )

    arguments, _ = parser.parse_known_args()

    show_app(
        data_dir=Path(
            arguments.data_dir
        ).expanduser().resolve(),
        explicit_csv=(
            Path(arguments.csv).expanduser().resolve()
            if arguments.csv
            else None
        ),
    )
