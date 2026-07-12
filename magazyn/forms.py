from flask_wtf import FlaskForm
from wtforms import DecimalField, IntegerField, PasswordField, StringField
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional

from .constants import ALL_SIZES


class LoginForm(FlaskForm):
    username = StringField("username", validators=[DataRequired()])
    password = PasswordField("password", validators=[DataRequired()])


class AddItemForm(FlaskForm):
    sizing_mode = StringField("sizing_mode", default="sized")
    category = StringField("category", validators=[DataRequired()])
    brand = StringField("brand", validators=[Optional()])
    series = StringField("series", validators=[Optional()])
    color = StringField("color", validators=[DataRequired()])
    custom_color = StringField("custom_color")


class ProductEditForm(FlaskForm):
    sizing_mode = StringField("sizing_mode", validators=[DataRequired()])
    category = StringField("category", validators=[DataRequired()])
    brand = StringField("brand", validators=[Optional()])
    series = StringField("series", validators=[Optional()])
    color = StringField("color", validators=[DataRequired()])


class FixedCostForm(FlaskForm):
    name = StringField("name", validators=[DataRequired()])
    amount = DecimalField("amount", validators=[InputRequired()])
    description = StringField("description", validators=[Optional()])


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
    setattr(
        ProductEditForm,
        f"quantity_{_size}",
        IntegerField(
            f"quantity_{_size}",
            default=0,
            validators=[NumberRange(min=0)],
        ),
    )
    setattr(ProductEditForm, f"barcode_{_size}", StringField(f"barcode_{_size}"))
    setattr(
        ProductEditForm,
        f"purchase_price_{_size}",
        DecimalField(
            f"purchase_price_{_size}",
            validators=[Optional(), NumberRange(min=0)],
        ),
    )
