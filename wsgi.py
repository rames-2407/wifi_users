import sys
import logging

logging.basicConfig(stream=sys.stderr)
sys.stdout = sys.stderr  

sys.path.insert(0, "/opt/wifi_portal")

from app import app as application
