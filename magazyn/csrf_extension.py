from flask_wtf import CSRFProtect

# Shared CSRF extension so individual routes can be exempted when needed.
csrf = CSRFProtect()
