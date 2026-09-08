"""
Fetches electric-train timetables for all configured stations from
swrailway.gov.ua and writes a combined data/schedule.json for the
front-end to read.

Run this from your own machine or GitHub Actions (NOT from an
environment that blocks swrailway.gov.ua) — see README.md.

Usage:
    python fetch_and_build.py [YYYY-MM-DD]

If no date is given, defaults to today (Europe/Kyiv).
"""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from parse_schedule import parse_schedule_html

BASE_URL = "https://swrailway.gov.ua/timetable/eltrain/"
HEADERS = {
    # A normal browser User-Agent; be a polite, infrequent, single caller.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

SCRIPT_DIR = Path(__file__).parent
STATIONS_FILE = SCRIPT_DIR / "stations.json"
OUTPUT_FILE = SCRIPT_DIR.parent / "data" / "schedule.json"

# How many days ahead to fetch (today + N-1 more days), so the front-end
# can show "today" and "tomorrow" without an extra run.
DAYS_AHEAD = 2

# Be gentle with the source site: pause between requests.
REQUEST_DELAY_SECONDS = 2


def load_stations():
    with open(STATIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


def fetch_station_day_raw(station: dict, date_str: str) -> list:
    """Fetch and parse a station's page for one date, unfiltered."""
    params = {station["param"]: station["id"], "eventdate": date_str}
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return parse_schedule_html(resp.text, own_station_name=station["name"])


def _time_to_minutes(time_str):
    if not time_str:
        return None
    h, m = time_str.split(":")
    return int(h) * 60 + int(m)


def assign_segments(station_name: str, trains: list, segment_defs: list,
                     raw_by_station: dict, drop_unmatched: bool = False,
                     label_order: list = None) -> list:
    """Sort trains into this station's configured segments (checked in
    config order — first match wins). A train matches a segment if its
    tid is ALSO present in that specific counterpart station's own
    fetched data (proof the same physical train stops there too).
    Direction (toward/from) is determined by comparing this station's
    own time for that tid against the counterpart's time for the same
    tid — whichever station the train reaches earlier is the one it's
    coming *from*.

    Multiple segments may reuse the same label on purpose (e.g. a
    station with only two real directions collapses several
    counterpart checks into just two final buckets).

    Trains that match no configured segment land in a trailing 'Інше'
    group, unless drop_unmatched is set (for big hub stations where
    unmatched trains are just unrelated city lines/noise).

    Output groups are ordered per label_order (falling back to
    first-seen order, with 'Інше' always last) so the UI shows a
    stable, deliberately chosen sequence rather than whatever order
    trains happened to appear in the source table.
    """
    counterpart_names = {s["counterpart"] for s in segment_defs}
    tid_index = {
        name: {t["tid"]: t for t in raw_by_station.get(name, []) if t.get("tid")}
        for name in counterpart_names
    }

    buckets = {}
    leftover = []

    for train in trains:
        tid = train.get("tid")
        home_time = _time_to_minutes(train.get("departure") or train.get("arrival"))
        placed = False

        if tid:
            for seg in segment_defs:
                counterpart_train = tid_index.get(seg["counterpart"], {}).get(tid)
                if counterpart_train is None:
                    continue
                counterpart_time = _time_to_minutes(
                    counterpart_train.get("departure") or counterpart_train.get("arrival")
                )
                if home_time is None or counterpart_time is None:
                    continue
                label = seg["toward_label"] if home_time <= counterpart_time else seg["from_label"]
                buckets.setdefault(label, []).append(train)
                placed = True
                break

        if not placed:
            leftover.append(train)

    if leftover and not drop_unmatched:
        buckets.setdefault("Інше", []).extend(leftover)

    def sort_key(t):
        return t.get("departure") or t.get("arrival") or "99:99"

    order = list(label_order or [])
    for label in buckets:
        if label not in order and label != "Інше":
            order.append(label)
    if "Інше" in buckets:
        order.append("Інше")

    return [
        {"label": label, "trains": sorted(buckets[label], key=sort_key)}
        for label in order if label in buckets
    ]


def main():
    if len(sys.argv) > 1:
        start_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        start_date = datetime.now(ZoneInfo("Europe/Kyiv")).date()

    stations = load_stations()
    output = {
        "generated_at": datetime.now(ZoneInfo("Europe/Kyiv")).isoformat(),
        "days": [],
    }

    for day_offset in range(DAYS_AHEAD):
        date = start_date + timedelta(days=day_offset)
        date_str = date.isoformat()

        # Pass 1: fetch every station's raw (ungrouped) trains for this date.
        raw_by_station = {}
        for station in stations:
            print(f"Fetching {station['name']} ({date_str})...")
            try:
                raw_by_station[station["name"]] = fetch_station_day_raw(station, date_str)
            except Exception as exc:  # keep going even if one station fails
                print(f"  ! failed: {exc}")
                raw_by_station[station["name"]] = []
            time.sleep(REQUEST_DELAY_SECONDS)

        # Pass 2: group each station's trains by segment (direct,
        # tid-matched comparison against each configured counterpart
        # station, not a proxy/union of unrelated stations).
        day_entry = {"date": date_str, "stations": {}}
        for station in stations:
            trains = raw_by_station[station["name"]]
            day_entry["stations"][station["name"]] = {
                "groups": assign_segments(
                    station["name"],
                    trains,
                    station.get("segments", []),
                    raw_by_station,
                    drop_unmatched=station.get("drop_unmatched", False),
                    label_order=station.get("label_order"),
                ),
            }

        output["days"].append(day_entry)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
