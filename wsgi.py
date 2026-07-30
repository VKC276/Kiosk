"""WSGI-entry för Gunicorn.

Bakgrundstrådar startas en gång via start_background_threads().
"""

from app import SHOULD_RUN, app, start_background_threads

start_background_threads()

# Kör lokalt: python wsgi.py
if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=8081, debug=False)
    finally:
        SHOULD_RUN = False
