from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, IntegerField
from wtforms.validators import DataRequired, NumberRange, Optional

from .constants import ALL_SIZES, PRODUCT_CATEGORIES, PRODUCT_BRANDS, PRODUCT_SERIES


class LoginForm(FlaskForm):
    username = StringField("username", validators=[DataRequired()])
    password = PasswordField("password", validators=[DataRequired()])


class AddItemForm(FlaskForm):
    category = SelectField(
        "category",
        choices=[(c, c) for c in PRODUCT_CATEGORIES],
        validators=[DataRequired()],
    )
    brand = SelectField(
        "brand",
        choices=[(b, b) for b in PRODUCT_BRANDS] + [("Inna", "Inna marka")],
        default="Truelove",
    )
    series = SelectField(
        "series",
        choices=[("", "-- Brak serii --")] + [(s, s) for s in PRODUCT_SERIES],
        validators=[Optional()],
    )
    color = SelectField(
        "color",
        choices=[
            ("Czerwony", "Czerwony"),
            ("Niebieski", "Niebieski"),
            ("Zielony", "Zielony"),
            ("Czarny", "Czarny"),
            ("Biały", "Biały"),
            ("Brązowy", "Brązowy"),
            ("Różowy", "Różowy"),
            ("Fioletowy", "Fioletowy"),
            ("Srebrny", "Srebrny"),
            ("Pomarańczowy", "Pomarańczowy"),
            ("Turkusowy", "Turkusowy"),
            ("Żółty", "Żółty"),
            ("Szary", "Szary"),
            ("Złoty", "Złoty"),
            ("Beżowy", "Beżowy"),
            ("Khaki", "Khaki"),
            ("Bordowy", "Bordowy"),
            ("Granatowy", "Granatowy"),
            ("Kremowy", "Kremowy"),
            ("Inny", "Inny (wpisz poniżej)"),
        ],
        validators=[DataRequired()],
    )
    custom_color = StringField("custom_color")


# Dynamically add quantity and barcode fields for each size
for _size in ALL_SIZES:
    setattr(
        AddItemForm,
        f"quantity_{_size}",
        IntegerField(
            f"quantity_{_size}",
            default=0,
            validators=[NumberRange(min=0)],
        ),
    )
    setattr(AddItemForm, f"barcode_{_size}", StringField(f"barcode_{_size}"))
