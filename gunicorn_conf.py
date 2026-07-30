"""Valfri Gunicorn-konfig.

Servicefilen behöver normalt inte `-c gunicorn_conf.py` eftersom
wsgi.py redan startar bakgrundstrådar. Filen finns kvar om man vill
flytta trådstart till post_worker_init.
"""


def post_worker_init(worker):
    from app import start_background_threads

    start_background_threads()
