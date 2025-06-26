from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, IntegerField
from wtforms.validators import DataRequired, NumberRange

from .constants import ALL_SIZES

class LoginForm(FlaskForm):
    username = StringField('username', validators=[DataRequired()])
    password = PasswordField('password', validators=[DataRequired()])

class AddItemForm(FlaskForm):
    name = StringField('name', validators=[DataRequired()])
    color = SelectField(
        'color',
        choices=[
            ('Czerwony', 'Czerwony'),
            ('Niebieski', 'Niebieski'),
            ('Zielony', 'Zielony'),
            ('Czarny', 'Czarny'),
            ('Biały', 'Biały'),
        ],
        validators=[DataRequired()],
    )


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
