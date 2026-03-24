import json
import os

STORAGE_FILE = "seen_listings.json"


def load_seen() -> set:
    if os.path.exists(STORAGE_FILE):
        with open(STORAGE_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(STORAGE_FILE, "w") as f:
        json.dump(list(seen), f)
