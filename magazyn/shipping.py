from flask import Blueprint, render_template, request, redirect, url_for, flash
from .auth import login_required
from pathlib import Path
import pandas as pd

bp = Blueprint("shipping", __name__)

ALLEGRO_COSTS_FILE = (
    Path(__file__).resolve().parent
    / "samples"
    / "deliveries_allegro.xlsx"
)


def load_costs(file_path: Path = ALLEGRO_COSTS_FILE) -> pd.DataFrame:
    """Load Allegro shipping costs from Excel."""
    try:
        return pd.read_excel(file_path, header=1)
    except Exception:
        return pd.DataFrame()


def save_costs(df: pd.DataFrame, file_path: Path = ALLEGRO_COSTS_FILE) -> None:
    """Save costs DataFrame back to Excel."""
    df.to_excel(file_path, index=False)


@bp.route("/shipping_costs", methods=["GET", "POST"])
@login_required
def shipping_costs():
    df = load_costs()
    columns = list(df.columns)
    # Ensure numeric columns are floats to avoid dtype warnings
    try:
        df[columns[1:]] = df[columns[1:]].astype(float)
    except (ValueError, TypeError):
        pass
    if request.method == "POST":
        for r in range(len(df)):
            for c_idx, col in enumerate(columns[1:]):
                key = f"val_{r}_{c_idx}"
                val_raw = request.form.get(key, "0")
                try:
                    val = float(val_raw)
                except ValueError:
                    val = val_raw
                df.at[r, col] = val
        save_costs(df)
        flash("Zapisano koszty wysyłek.")
        return redirect(url_for("shipping.shipping_costs"))

    rows = df.to_dict(orient="records")
    return render_template(
        "shipping_costs.html", columns=columns, rows=rows
    )
