from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, IntegerField
from wtforms.validators import DataRequired, NumberRange

from .constants import ALL_SIZES


class LoginForm(FlaskForm):
    username = StringField("username", validators=[DataRequired()])
    password = PasswordField("password", validators=[DataRequired()])


class AddItemForm(FlaskForm):
    name = StringField("name", validators=[DataRequired()])
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
