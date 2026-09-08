"""
Parser for swrailway.gov.ua electric-train timetable pages
(https://swrailway.gov.ua/timetable/eltrain/?sid=<id>&eventdate=<date>
 or ?geo=<id>&eventdate=<date>).

Extracts the list of trains shown in the "Потяги" (trains) table.
"""
from bs4 import BeautifulSoup


def parse_schedule_html(html: str, own_station_name: str = None):
    """Parse one timetable page's HTML and return a list of train dicts.

    Each dict has: number, tid, frequency, route, stop, arrival,
    departure, valid_from, valid_to.

    Single-station pages (?sid=...) render an 8-column table with no
    "Зупинка" (stop) column, since every row is implicitly at that one
    station — pass its name as own_station_name to fill that field.
    Hub pages (?geo=...) render a 9-column table with an explicit
    "Зупинка" column identifying which platform each row belongs to.
    """
    soup = BeautifulSoup(html, "html.parser")

    trains_tab = soup.find(id="tabs-trains")
    if trains_tab is None:
        # Page structure changed, or no schedule for this station/date.
        return []

    rows = trains_tab.find_all("tr", class_=["on", "onx"])
    results = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) not in (8, 9):
            # Not a data row (could be a spacer or a header row)
            continue

        has_stop_column = len(cells) == 9

        number_link = cells[0].find("a")
        number = number_link.get_text(strip=True) if number_link else cells[0].get_text(strip=True)
        tid = None
        if number_link and number_link.get("href"):
            href = number_link["href"]
            if "tid=" in href:
                tid = href.split("tid=")[-1]

        frequency = cells[2].get_text(strip=True)
        route = cells[3].get_text(strip=True)

        if has_stop_column:
            stop_link = cells[4].find("a")
            stop = stop_link.get_text(strip=True) if stop_link else cells[4].get_text(strip=True)
            arrival = cells[5].get_text(strip=True)
            departure = cells[6].get_text(strip=True)
            valid_from = cells[7].get_text(strip=True)
            valid_to = cells[8].get_text(strip=True)
        else:
            stop = own_station_name
            arrival = cells[4].get_text(strip=True)
            departure = cells[5].get_text(strip=True)
            valid_from = cells[6].get_text(strip=True)
            valid_to = cells[7].get_text(strip=True)

        if not number or not route or not number[0].isdigit():
            # Skips the header row ("№", "Маршрут прямування", ...)
            continue

        results.append({
            "number": number,
            "tid": tid,
            "frequency": frequency,
            "route": route,
            "stop": stop,
            "arrival": None if arrival == "–" else arrival,
            "departure": None if departure == "–" else departure,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "direction": classify_direction(route),
        })

    return results


def classify_direction(route: str) -> str:
    """Classify a train as moving 'away_from_kyiv' or 'toward_kyiv' based
    on which side of the 'Звідки – Куди' route string a Kyiv station name
    appears on. Returns 'unknown' if neither/both sides mention Kyiv
    (e.g. a route that doesn't touch Kyiv at all)."""
    parts = route.split("–")
    if len(parts) != 2:
        return "unknown"
    origin, destination = parts[0].strip(), parts[1].strip()
    origin_is_kyiv = origin.startswith("Київ")
    destination_is_kyiv = destination.startswith("Київ")
    if origin_is_kyiv and not destination_is_kyiv:
        return "away_from_kyiv"
    if destination_is_kyiv and not origin_is_kyiv:
        return "toward_kyiv"
    return "unknown"


def filter_by_direction(trains, keywords):
    """Keep only trains whose route mentions any of the given keywords
    (e.g. ['Ніжин', 'Фастів']). Case-sensitive substring match, matches
    against the full 'Звідки – Куди' route string so either origin or
    destination counts."""
    if not keywords:
        return trains
    return [t for t in trains if any(kw in t["route"] for kw in keywords)]


if __name__ == "__main__":
    # Quick self-test against the sample page Eugene provided.
    with open("/home/claude/kyiv-pass.html", encoding="utf-8", errors="replace") as f:
        html = f.read()

    all_trains = parse_schedule_html(html)
    print(f"Parsed {len(all_trains)} trains total")
    print(all_trains[0])
    print(all_trains[3])

    filtered = filter_by_direction(all_trains, ["Ніжин", "Фастів"])
    print(f"Filtered to {len(filtered)} trains toward Ніжин/Фастів")
    for t in filtered[:5]:
        print(t["number"], t["route"], t["departure"], t["arrival"])
