import os
import sys

# Ensure the root project directory is added to sys.path so modules like app, config, database, routes are discoverable
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app
