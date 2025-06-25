from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, IntegerField
from wtforms.validators import DataRequired

class LoginForm(FlaskForm):
    username = StringField('username', validators=[DataRequired()])
    password = PasswordField('password', validators=[DataRequired()])

class AddItemForm(FlaskForm):
    name = StringField('name', validators=[DataRequired()])
    color = SelectField('color', choices=[
        ('Czerwony', 'Czerwony'),
        ('Niebieski', 'Niebieski'),
        ('Zielony', 'Zielony'),
        ('Czarny', 'Czarny'),
        ('Biały', 'Biały'),
    ], validators=[DataRequired()])
    barcode = StringField('barcode')
    # Fields for each size
    quantity_XS = IntegerField('quantity_XS', default=0)
    barcode_XS = StringField('barcode_XS')
    quantity_S = IntegerField('quantity_S', default=0)
    barcode_S = StringField('barcode_S')
    quantity_M = IntegerField('quantity_M', default=0)
    barcode_M = StringField('barcode_M')
    quantity_L = IntegerField('quantity_L', default=0)
    barcode_L = StringField('barcode_L')
    quantity_XL = IntegerField('quantity_XL', default=0)
    barcode_XL = StringField('barcode_XL')
    quantity_Uniwersalny = IntegerField('quantity_Uniwersalny', default=0)
    barcode_Uniwersalny = StringField('barcode_Uniwersalny')
