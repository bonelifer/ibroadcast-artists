#!/usr/bin/env python3
"""
Fetch all artist names from an iBroadcast library and write a deduplicated,
sorted list to a text file.

iBroadcast's library data model has a single "artists" collection; albums
and tracks each reference an artist by artist_id into that same table (there
is no separate "album artist" field distinct from "artist" in the API). So
this pulls the one artist list, which covers both uses.

Many "artist" entries are really multiple artists joined into one string
(e.g. "Artist A & Artist B"). These are split out of the main output into
per-separator files alongside it, so the main file stays single-artist-only.
See categorize_artist_names() for the exact rule.

Authentication uses the OAuth 2 Device Code Flow, which requires a
client_id registered at media.ibroadcast.com (side menu -> Apps ->
"developer" link at the bottom -> create an app). The resulting tokens are
cached locally so re-runs don't require re-authorizing in a browser.

Settings (client_id, output path, token cache path) can be supplied via
config.ini instead of command-line flags; copy config.ini.example to
config.ini and fill it in. Precedence is: command-line flags, then
config.ini, then the built-in defaults below.
"""

import argparse
import configparser
import json
import re
import sys
from pathlib import Path

import ibroadcast

DEFAULT_CONFIG_FILE = Path(__file__).parent / "config.ini"
DEFAULT_TOKEN_FILE = Path(__file__).parent / ".ibroadcast_token.json"
DEFAULT_OUTPUT_FILE = Path(__file__).parent / "artists.txt"
SCOPES = ["user.library:read"]

# Multi-artist join separators, in priority order: a name is bucketed under
# the first one it matches. E.g. a name containing both "feat." and "&" goes
# to "feat", since "feat" is checked before "/" and "&".
SEPARATOR_RULES: list[tuple[str, re.Pattern]] = [
    (
        "feat",
        re.compile(
            r"\bfeat\.?\b|\bfeaturing\b|\bft\.?\b"
            # Also catch a missing space before "feat."/"featuring" (e.g.
            # "Home Freefeat. Don McLean"). Excludes "ft" here since without
            # a word boundary it false-matches ordinary words like "Left"
            # or "Soft".
            r"|(?<=[a-zA-Z])(?:feat\.|featuring)",
            re.IGNORECASE,
        ),
    ),
    ("slash", re.compile(r"/")),
    ("ampersand", re.compile(r"&")),
    ("with", re.compile(r"\bwith\b", re.IGNORECASE)),
    ("and", re.compile(r"\band\b", re.IGNORECASE)),
    ("comma", re.compile(r",")),
    ("dash", re.compile(r" - ")),
    ("plus", re.compile(r" \+ ")),
    ("x", re.compile(r" x ", re.IGNORECASE)),
    ("orch", re.compile(r"\borch\.?\b", re.IGNORECASE)),
]


def load_config(config_file: Path) -> configparser.SectionProxy:
    """Return the [ibroadcast] section of config_file.

    An empty section is returned if the file or the section is absent.
    """
    config = configparser.ConfigParser()
    if config_file.exists():
        config.read(config_file, encoding="utf-8")
    if not config.has_section("ibroadcast"):
        config.add_section("ibroadcast")
    return config["ibroadcast"]


def load_token_set(token_file: Path):
    """Return a saved token dict from token_file, or None if not present."""
    if not token_file.exists():
        return None
    with token_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_token_set(token_file: Path, token_set) -> None:
    """Persist a TokenSet to token_file as JSON."""
    with token_file.open("w", encoding="utf-8") as f:
        json.dump(token_set.to_dict(), f)


def authenticate(client_id: str, token_file: Path):
    """Return an authenticated iBroadcast client.

    A cached token is reused when possible.
    """
    saved = load_token_set(token_file)
    if saved:
        token_set = ibroadcast.oauth.TokenSet.from_dict(saved)
        if token_set.is_expired:
            # iBroadcast's "library" endpoint returns a hard failure for an
            # expired access token rather than the soft "authenticated: false"
            # signal the client library's own auto-refresh relies on, so we
            # refresh proactively here instead of waiting for that to trigger.
            if not client_id:
                raise SystemExit(
                    "Cached access token has expired and no client_id is "
                    "available "
                    "to refresh it; pass --client-id or set it in config.ini."
                )
            token_set = ibroadcast.oauth.refresh_access_token(
                client_id, token_set.refresh_token
            )
            save_token_set(token_file, token_set)
        client = ibroadcast.from_token_set(
            token_set,
            client_id=client_id,
            token_refreshed_callback=lambda ts: save_token_set(token_file, ts),
        )
        return client

    client = ibroadcast.from_device_code(client_id=client_id, scopes=SCOPES)
    save_token_set(token_file, client.token_set)
    return client


def fetch_artist_names(client) -> list[str]:
    """Download the library and return deduplicated, sorted artist names."""
    client.refresh()
    names = {artist["name"] for artist in client.artists.values()}
    return sorted(names, key=str.casefold)


TRACK_NUMBER_PREFIX = re.compile(r"^\d{1,3}\s+(.+)$")


def strip_track_number_contamination(names: list[str]) -> list[str]:
    """Drop names that are a clean artist name with a leading track number.

    Some library entries are mis-tagged (e.g. "02 Merle Haggard") where a
    track number leaked into the artist field. If the un-prefixed remainder
    ("Merle Haggard") is also present as its own entry, the prefixed one is
    dropped as a duplicate. Genuine numeric-leading artist names (e.g. "38
    Special", "69 Boyz") are left alone, since their remainder ("Special",
    "Boyz") isn't itself a separate artist in the library.
    """
    name_set = set(names)
    contaminated = {
        name
        for name in names
        if (match := TRACK_NUMBER_PREFIX.match(name))
        and match.group(1) in name_set
    }
    return [name for name in names if name not in contaminated]


# iBroadcast placeholder names for tracks with no real artist tag, not
# actual artists; dropped entirely rather than written to any file.
PLACEHOLDER_ARTIST_NAMES = {"[no artist]", "[traditional]", "[unknown]"}


def drop_placeholder_names(names: list[str]) -> list[str]:
    """Drop known iBroadcast placeholder artist names."""
    return [
        name
        for name in names
        if name.casefold() not in PLACEHOLDER_ARTIST_NAMES
    ]


CURLY_APOSTROPHE = "’"


def merge_apostrophe_variants(names: list[str]) -> list[str]:
    """Drop curly-apostrophe names that duplicate a straight-apostrophe name.

    Some library entries use a typographic right single quote (U+2019, e.g.
    "Edgar Winter’s White Trash") instead of a plain apostrophe (e.g.
    "Edgar Winter's White Trash"), creating an exact-match duplicate. If the
    straight-apostrophe form also exists as its own entry, the curly one is
    dropped; names whose only form uses the curly apostrophe (e.g. "Guns
    N’ Roses", which has no straight-apostrophe counterpart) are left alone.
    """
    name_set = set(names)
    duplicates = {
        name
        for name in names
        if CURLY_APOSTROPHE in name
        and (straight := name.replace(CURLY_APOSTROPHE, "'")) != name
        and straight in name_set
    }
    return [name for name in names if name not in duplicates]


MISSING_SPACE_FEAT = re.compile(
    r"(?<=[a-zA-Z])(feat\.|featuring)", re.IGNORECASE
)


def strip_missing_space_feat_duplicates(names: list[str]) -> list[str]:
    """Drop "Xfeat. Y" names (missing space before "feat.") that duplicate
    the correctly-spaced "X feat. Y" form.

    E.g. "Home Freefeat. Don McLean" is dropped because "Home Free feat.
    Don McLean" already exists as its own entry. A name with this typo but
    no correctly-spaced duplicate (e.g. "Home Freefeat. Texas Hill") is left
    as-is rather than inventing a corrected name not present in the library.
    """
    name_set = set(names)
    duplicates = {
        name
        for name in names
        if (match := MISSING_SPACE_FEAT.search(name))
        and (name[: match.start()] + " " + name[match.start() :]) in name_set
    }
    return [name for name in names if name not in duplicates]


def categorize_artist_names(names: list[str]) -> dict[str, list[str]]:
    """Split artist names into single-artist and multi-artist-join buckets.

    Each name is tested against SEPARATOR_RULES in order and placed in the
    first bucket that matches; names matching none of them are "plain"
    (genuine single-artist entries). Relative order within each bucket is
    preserved from the input.
    """
    buckets: dict[str, list[str]] = {"plain": []}
    for bucket_name, _ in SEPARATOR_RULES:
        buckets[bucket_name] = []

    for name in names:
        for bucket_name, pattern in SEPARATOR_RULES:
            if pattern.search(name):
                buckets[bucket_name].append(name)
                break
        else:
            buckets["plain"].append(name)

    return buckets


def write_artist_files(
    names: list[str], output: Path
) -> dict[str, tuple[Path, int]]:
    """Write single-artist names to output, each join category to its own file.

    Join-category files are named "<output stem>-<category><output suffix>"
    in output's directory (e.g. artists.txt -> artists-ampersand.txt).
    Returns {bucket_name: (path, count)} for reporting.
    """
    buckets = categorize_artist_names(names)
    stem = output.stem
    suffix = output.suffix or ".txt"

    written: dict[str, tuple[Path, int]] = {}

    output.write_text("\n".join(buckets["plain"]) + "\n", encoding="utf-8")
    written["plain"] = (output, len(buckets["plain"]))

    for bucket_name, _ in SEPARATOR_RULES:
        path = output.with_name(f"{stem}-{bucket_name}{suffix}")
        path.write_text(
            "\n".join(buckets[bucket_name]) + "\n", encoding="utf-8"
        )
        written[bucket_name] = (path, len(buckets[bucket_name]))

    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a deduplicated list of iBroadcast artist names "
        "to a text file."
    )
    parser.add_argument(
        "-c",
        "--client-id",
        help="iBroadcast OAuth2 client_id (from media.ibroadcast.com -> "
        "Apps -> developer). "
        "Only required the first time; ignored on later runs if a cached "
        "token exists. "
        "Falls back to config.ini's client_id if not given.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output text file (default: config.ini's output, else "
        f"{DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "-t",
        "--token-file",
        type=Path,
        help="Where to cache OAuth tokens (default: config.ini's "
        f"token_file, else {DEFAULT_TOKEN_FILE})",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_FILE,
        help="Config file to read settings from (default: "
        f"{DEFAULT_CONFIG_FILE})",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    client_id = args.client_id or config.get("client_id") or None
    output = args.output or Path(
        config.get("output", fallback=str(DEFAULT_OUTPUT_FILE))
    )
    token_file = args.token_file or Path(
        config.get("token_file", fallback=str(DEFAULT_TOKEN_FILE))
    )

    if not token_file.exists() and not client_id:
        parser.error(
            "client_id is required for the first run (no cached token found); "
            "pass --client-id or set it in config.ini"
        )

    client = authenticate(client_id, token_file)
    artist_names = fetch_artist_names(client)

    cleaned_names = strip_track_number_contamination(artist_names)
    dropped = len(artist_names) - len(cleaned_names)
    if dropped:
        print(f"Dropped {dropped} track-number-contaminated duplicate name(s)")

    before_placeholder_drop = len(cleaned_names)
    cleaned_names = drop_placeholder_names(cleaned_names)
    placeholder_dropped = before_placeholder_drop - len(cleaned_names)
    if placeholder_dropped:
        print(f"Dropped {placeholder_dropped} placeholder artist name(s)")

    before_apostrophe_merge = len(cleaned_names)
    cleaned_names = merge_apostrophe_variants(cleaned_names)
    apostrophe_merged = before_apostrophe_merge - len(cleaned_names)
    if apostrophe_merged:
        print(
            f"Dropped {apostrophe_merged} curly-apostrophe duplicate name(s)"
        )

    before_missing_space_drop = len(cleaned_names)
    cleaned_names = strip_missing_space_feat_duplicates(cleaned_names)
    missing_space_dropped = before_missing_space_drop - len(cleaned_names)
    if missing_space_dropped:
        print(
            f"Dropped {missing_space_dropped} missing-space-before-feat "
            "duplicate name(s)"
        )

    written = write_artist_files(cleaned_names, output)
    plain_path, plain_count = written["plain"]
    print(f"Wrote {plain_count} single-artist names to {plain_path}")
    for bucket_name, _ in SEPARATOR_RULES:
        path, count = written[bucket_name]
        print(f"Wrote {count} names to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
