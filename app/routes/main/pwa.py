import os
from flask import send_from_directory, current_app
from . import main_bp


@main_bp.route('/sw.js')
def service_worker():
    return send_from_directory(
        os.path.join(current_app.root_path, 'static'),
        'sw.js',
        mimetype='application/javascript'
    )
