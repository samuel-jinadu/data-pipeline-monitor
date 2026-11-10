from pathlib import Path
import polars as pl
import streamlit as st

st.set_page_config(page_title="Data Pipeline Monitor", layout="wide")

DATA_DIR = Path(__file__).parent / "data"

@st.cache_data(show_spinner="Loading warehouse snapshot…")
def load_tables() -> dict[str, pl.DataFrame]:
    return {p.stem: pl.read_parquet(p) for p in sorted(DATA_DIR.glob("*.parquet"))}

tables = load_tables()

st.title("Data Pipeline Monitor")
st.caption("Self-contained data quality monitor — synthetic warehouse from chaoslake.")

c1, c2 = st.columns(2)
c1.metric("Tables", len(tables))
c2.metric("Total rows", f"{sum(len(d) for d in tables.values()):,}")

st.subheader("Sample data")
for name, df in tables.items():
    st.markdown(f"**`{name}`** - {len(df):,} rows × {df.width} columns")

st.subheader("Null Report")

# Build consolidated report — this is the M3 null_report() function
rows = []
for name, df in tables.items():
    for col in df.columns:
        n = df[col].null_count()
        if n == 0:
            continue  # only problem columns
        rows.append({
            "table": name,
            "column": col,
            "nulls": n,
            "pct": round(n / df.height * 100, 2),
        })

if not rows:
    st.success("✅ No nulls detected across any table.")
else:
    null_df = pl.DataFrame(rows).sort(["table", "nulls"], descending=[False, True])

    # Summary metrics
    c1, c2, c3 = st.columns(3)
    worst = null_df.row(0, named=True)
    c1.metric("Affected columns", len(null_df))
    c2.metric("Total nulls", f"{null_df['nulls'].sum():,}")
    c3.metric(
        "Worst", f"`{worst['table']}.{worst['column']}`",
        delta=f"{worst['nulls']} nulls ({worst['pct']}%)",
        delta_color="inverse",
    )

    # Report table
    st.dataframe(
        null_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "table":   st.column_config.TextColumn("Table"),
            "column":  st.column_config.TextColumn("Column"),
            "nulls":   st.column_config.NumberColumn("Nulls", format="%d"),
            "pct":     st.column_config.ProgressColumn(
                "Null %", format="%.2f%%", min_value=0, max_value=10,
            ),
        },
    )


st.subheader("Duplicate Report")

def duplicate_report(tables: dict[str, pl.DataFrame]) -> pl.DataFrame:
    rows = []
    for name, df in tables.items():
        total = df.height
        # Full-row duplicates: chaoslake appends copies of existing rows
        full_dupe = total - df.unique().height
        # Business-key duplicates: excluding the surrogate PK, what a real
        # monitor would flag as an idempotency bug
        non_pk = [c for c in df.columns if c != "id"]
        biz_dupe = total - df.select(non_pk).unique().height if non_pk else 0
        rows.append({
            "table": name,
            "rows": total,
            "unique_rows": df.unique().height,
            "dupe_rows": full_dupe,
            "dupe_pct": round(full_dupe / total * 100, 2) if total else 0.0,
            "biz_key_dupes": biz_dupe,
        })
    return pl.DataFrame(rows)

report = duplicate_report(tables)
total_dupes = int(report["dupe_rows"].sum())

if total_dupes == 0:
    st.success("✅ No duplicate rows detected across any table.")
else:
    worst = report.sort("dupe_rows", descending=True).row(0, named=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Tables affected", int((report["dupe_rows"] > 0).sum()))
    c2.metric("Total duplicate rows", f"{total_dupes:,}")
    c3.metric(
        "Worst",
        f"`{worst['table']}`",
        delta=f"{worst['dupe_rows']} dupes ({worst['dupe_pct']}%)",
        delta_color="inverse",
    )

    st.dataframe(
        report,
        use_container_width=True,
        hide_index=True,
        column_config={
            "table":          st.column_config.TextColumn("Table"),
            "rows":           st.column_config.NumberColumn("Rows", format="%d"),
            "unique_rows":    st.column_config.NumberColumn("Unique", format="%d"),
            "dupe_rows":      st.column_config.NumberColumn("Dupes", format="%d"),
            "dupe_pct":       st.column_config.ProgressColumn(
                "Dupe %", format="%.2f%%", min_value=0, max_value=5,
            ),
            "biz_key_dupes":  st.column_config.NumberColumn(
                "Biz-key dupes", format="%d",
                help="Duplicates counting all columns except `id`",
            ),
        },
    )

