"""Test package.

Set before src.config is imported: the suite asserts how the worker behaves
when a variable is NOT set, so it must not inherit a developer's local .env.
"""
import os

os.environ["SKIP_DOTENV"] = "1"
