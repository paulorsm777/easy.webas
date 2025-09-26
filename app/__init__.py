"""
Playwright Automation Server

A powerful FastAPI server for executing Playwright scripts with queue management,
video recording, and comprehensive monitoring capabilities.
"""

__version__ = "1.0.0"
__author__ = "Playwright Automation Team"

from .config import settings
from .logger import setup_logging

# Initialize logging when module is imported
setup_logging()
