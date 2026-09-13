"""WSGI-entry för Gunicorn.

Bakgrundstrådar startas en gång via start_background_threads().
"""

from app import SERVER_HOST, SERVER_PORT, SHOULD_RUN, app, start_background_threads

start_background_threads()

# Kör lokalt: python wsgi.py
if __name__ == '__main__':
    try:
        app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False)
    finally:
        SHOULD_RUN = False
