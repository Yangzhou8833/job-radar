"""Point every test at the example profile and a throwaway data folder."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ["JOB_RADAR_PROFILE"] = os.path.join(ROOT, "profile", "profile.example.toml")
os.environ["JOB_RADAR_DATA"] = tempfile.mkdtemp(prefix="job-radar-test-")

from jobradar import config  # noqa: E402

config.reset()


def profile_from(text):
    """A Profile built from TOML text, for tests that need other settings than the example."""
    import tomllib
    return config.Profile(tomllib.loads(text))


MINIMAL = """
[candidate]
name = "Test"
career_stage = "{stage}"
years_experience = 1
[scope]
countries = ["DE"]
[languages]
english = "C1"
german = "{german}"
[directions]
marketing = ["marketing", "brand"]
"""
