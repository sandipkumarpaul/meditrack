from flask import Blueprint

main_bp = Blueprint('main', __name__)

# Submodules register their routes on main_bp via decorators as a side
# effect of being imported -- keep this import at the bottom so `main_bp`
# already exists in this module's namespace when they do `from . import main_bp`.
from . import dashboard, profiles, medications, history, medex, notifications, pwa  # noqa: E402,F401
