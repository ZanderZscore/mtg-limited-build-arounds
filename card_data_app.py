"""Explore individual card win rates, build-around potential, and card-pair synergy.

Run:
    pip install streamlit pandas numpy
    streamlit run app.py -- --csv 'SOS_car_pairs(1).csv'
"""

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="MTG Build-Around Explorer", page_icon="🃏", layout="wide")

REQUIRED_COLUMNS = {"card_name_1", "card_name_2", "win_rate", "game_count"}
DEFAULT_CSV = Path(__file__).resolve().parent / "SOS_car_pairs(1).csv"


@st.cache_data(show_spinner="Loading card data…")
def load_data(csv_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = pd.read_csv(
        csv_path,
        usecols=lambda col: col in REQUIRED_COLUMNS,
        dtype={"card_name_1": "string", "card_name_2": "string",
               "win_rate": "float64", "game_count": "int64"},
    )
    missing = REQUIRED_COLUMNS - set(data.columns)
    if missing:
        raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
    data = data.dropna(subset=list(REQUIRED_COLUMNS))
    data = data.loc[data["game_count"].gt(0) & data["win_rate"].between(0, 1)].copy()

    # Diagonal rows represent TRUE individual game-in-hand win rates / unique game counts.
    diagonal = data.loc[data.card_name_1.eq(data.card_name_2)].copy()
    if diagonal.card_name_1.duplicated().any():
        raise ValueError("Found duplicate individual-card (diagonal) rows in the CSV.")
    individual = diagonal.rename(columns={
        "card_name_1": "card", "win_rate": "individual_wr", "game_count": "games"
    })[["card", "individual_wr", "games"]]

    pairs = data.loc[data.card_name_1.ne(data.card_name_2)].copy()
    if pairs.duplicated(["card_name_1", "card_name_2"]).any():
        raise ValueError("Found duplicate ordered card pairs in the CSV.")
    return individual, pairs


@st.cache_data(show_spinner="Calculating build-around statistics…")
def calculate_statistics(individual: pd.DataFrame, pairs: pd.DataFrame):
    own = individual[["card", "individual_wr"]].rename(
        columns={"card": "card_name_1", "individual_wr": "wr_1"}
    )
    other = individual[["card", "individual_wr"]].rename(
        columns={"card": "card_name_2", "individual_wr": "wr_2"}
    )
    enriched = pairs.merge(own, on="card_name_1", how="left", validate="many_to_one")
    enriched = enriched.merge(other, on="card_name_2", how="left", validate="many_to_one")
    # Both individual baselines are necessary to calculate improvement and synergy.
    enriched = enriched.dropna(subset=["wr_1", "wr_2"]).copy()
    enriched["improvement"] = enriched.win_rate - enriched.wr_1
    enriched["synergy"] = enriched.win_rate - enriched[["wr_1", "wr_2"]].max(axis=1)

    def summarize(group: pd.DataFrame) -> pd.Series:
        # Every eligible partner counts equally; no sample-size weighting or shrinkage.
        # ceil() selects at least one partner for a card with fewer than ten pairings.
        best_n = max(1, math.ceil(len(group) * 0.10))
        return pd.Series({
            "variance": group.win_rate.var(ddof=0),
            "build_around": group.synergy.nlargest(best_n).mean(),
            "pair_count": len(group),
            "best_partner": group.sort_values(
                ["synergy", "card_name_2"], ascending=[False, True]
            ).iloc[0].card_name_2,
        })

    if enriched.empty:
        summaries = pd.DataFrame(columns=[
            "card_name_1", "variance", "build_around", "pair_count", "best_partner"
        ])
    else:
        summaries = enriched.groupby("card_name_1", sort=False).apply(
            summarize, include_groups=False
        ).reset_index()

    summary = individual.merge(
        summaries, left_on="card", right_on="card_name_1", how="left"
    ).drop(columns="card_name_1")
    summary["pair_count"] = summary["pair_count"].fillna(0).astype(int)
    summary = summary.sort_values(
        ["build_around", "card"], ascending=[False, True], na_position="last"
    ).reset_index(drop=True)
    return summary, enriched


def show_app(csv_path: str) -> None:
    st.title("MTG Build-Around Explorer")
    st.caption("Individual game-in-hand win rates, upper-tail synergy, and pair win rates")

    try:
        individual, pairs = load_data(csv_path)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        st.error(f"Could not load CSV: {exc}")
        st.stop()
    if individual.empty:
        st.error("No individual-card rows found (card_name_1 == card_name_2).")
        st.stop()

    summary, enriched = calculate_statistics(individual, pairs)

    with st.sidebar:
        st.header("Explore")
        search = st.text_input("Find a card", placeholder="Type part of a name…")
        st.caption("Click a row in the first table to see its partners. Click column headings to sort.")
        st.divider()
        st.markdown("**Definitions**")
        st.caption("Build-around potential = unweighted mean of the top 10% of synergy scores for this card’s eligible pairings (rounding the number of partners up).")
        st.caption("Synergy = pair WR − max(individual WR of card 1, individual WR of card 2).")
        st.caption("Variance = unweighted population variance of a card’s pair win rates (in percentage-points squared).")
        st.caption("These are observed associations, not proof that one card causes another to win more.")

    view = summary.copy()
    if search:
        view = view.loc[view.card.str.contains(search, case=False, regex=False, na=False)]
    if view.empty:
        st.info("No cards match the search.")
        return

    st.subheader("Cards")
    st.caption("Default sort: highest build-around potential first. Mean WR is each card’s actual individual GIH win rate, not an average over pairs. Games counts distinct games containing that card.")
    display = view.copy()
    display["individual_wr"] *= 100
    display["build_around"] *= 100
    display["variance"] *= 10000
    display = display.rename(columns={
        "card": "Card", "individual_wr": "Mean WR", "variance": "Variance",
        "build_around": "Build-Around Potential", "games": "Games",
        "pair_count": "Pairings", "best_partner": "Best Partner"
    })[["Card", "Mean WR", "Variance", "Build-Around Potential", "Games", "Pairings", "Best Partner"]]
    display = display.reset_index(drop=True)
    picked = st.dataframe(
        display,
        hide_index=True,
        width='stretch',
        height=510,
        on_select="rerun",
        selection_mode="single-row",
        key="card_selection",
        column_config={
            "Card": st.column_config.TextColumn("Card", width="large"),
            "Mean WR": st.column_config.NumberColumn("Mean WR", format="%.2f%%"),
            "Variance": st.column_config.NumberColumn("Variance", format="%.2f"),
            "Build-Around Potential": st.column_config.NumberColumn("Build-Around Potential", format="%+.2f pp"),
            "Games": st.column_config.NumberColumn("Games", format="%d"),
            "Pairings": st.column_config.NumberColumn("Pairings", format="%d"),
            "Best Partner": st.column_config.TextColumn("Best Partner", width="large"),
        },
    )

    st.caption("Variance is expressed in percentage-points squared. Build-Around Potential is measured in percentage points (pp). Cards without eligible pairs have no build-around score.")
    if not picked.selection.rows:
        st.info("Select a card in the table above to inspect its pairings.")
        return

    selected_name = display.iloc[picked.selection.rows[0]]["Card"]
    selected = view.loc[view.card.eq(selected_name)].iloc[0]
    st.divider()
    st.subheader(f"Pairings for {selected_name}")
    a, b, c = st.columns(3)
    a.metric("Individual GIH WR", f"{selected.individual_wr:.2%}")
    b.metric("Build-Around Potential", "N/A" if pd.isna(selected.build_around) else f"{selected.build_around * 100:+.2f} pp")
    c.metric("Unique Games", f"{selected.games:,}")

    detail = enriched.loc[enriched.card_name_1.eq(selected_name)].copy()
    if detail.empty:
        st.info("No eligible pairings for this card.")
        return
    detail = detail.sort_values(["synergy", "game_count"], ascending=[False, False])
    detail["Pair WR"] = detail.win_rate * 100
    detail["WR Improvement"] = detail.improvement * 100
    detail["Synergy Score"] = detail.synergy * 100
    detail["Individual WR (Partner)"] = detail.wr_2 * 100
    detail = detail.rename(columns={"card_name_2": "Paired Card", "game_count": "Games"})
    st.caption("Default sort: highest synergy score first. WR Improvement compares the pair to the selected card; Synergy Score compares it to the stronger individual card. Both are in percentage points.")
    st.dataframe(
        detail[["Paired Card", "Synergy Score", "Pair WR", "WR Improvement", "Individual WR (Partner)", "Games"]].reset_index(drop=True),
        hide_index=True,
        width='stretch',
        height=620,
        column_config={
            "Paired Card": st.column_config.TextColumn("Paired Card", width="large"),
            "Pair WR": st.column_config.NumberColumn("Pair WR", format="%.2f%%"),
            "WR Improvement": st.column_config.NumberColumn("WR Improvement", format="%+.2f pp"),
            "Synergy Score": st.column_config.NumberColumn("Synergy Score", format="%+.2f pp"),
            "Individual WR (Partner)": st.column_config.NumberColumn("Individual WR (Partner)", format="%.2f%%"),
            "Games": st.column_config.NumberColumn("Games", format="%d"),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Streamlit MTG build-around explorer")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="Path to card-pair CSV")
    arguments, _ = parser.parse_known_args()
    show_app(arguments.csv)
