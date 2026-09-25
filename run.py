import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Debug mode (auto-reload + interactive debugger) must never be exposed
    # publicly, so it's opt-in via FLASK_DEBUG=1 rather than always on.
    debug = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes')
    print(f"Starting MediTrack on http://127.0.0.1:{port}")
    app.run(debug=debug, host='127.0.0.1', port=port)
