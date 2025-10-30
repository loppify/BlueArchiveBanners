import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

ASIA_URL = "https://bluearchive.wiki/wiki/Banner_List"
GLOBAL_URL = "https://bluearchive.wiki/wiki/Banner_List_(Global)"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/100.0.4896.88 Safari/537.36'
}
DATE_FORMAT = "%Y/%m/%d %H:%M"


@dataclass(frozen=True)
class Banner:
    image_url: str
    units: Tuple[str, ...]
    start: datetime
    end: datetime
    source: str
    release_type: str

    def matches_units(self, other_units: Tuple[str, ...]) -> bool:
        return set(self.units) == set(other_units)

    def matches(self, other: 'Banner') -> bool:
        return self.matches_units(other.units) and self.release_type == other.release_type


@dataclass
class MergedBanner:
    units: Tuple[str, ...]
    image_url: str
    asia_start: Optional[datetime] = None
    asia_end: Optional[datetime] = None
    asia_type: str = ""
    global_start: Optional[datetime] = None
    global_end: Optional[datetime] = None
    global_type: str = ""
    global_is_predicted: bool = False

    @property
    def start_str_asia(self) -> str:
        return self.asia_start.strftime('%Y-%m-%d') if self.asia_start else "N/A"

    @property
    def end_str_asia(self) -> str:
        return self.asia_end.strftime('%Y-%m-%d') if self.asia_end else "N/A"

    @property
    def start_str_global(self) -> str:
        if not self.global_start: return "N/A"
        suffix = " (Predicted)" if self.global_is_predicted else ""
        return self.global_start.strftime('%Y-%m-%d') + suffix

    @property
    def end_str_global(self) -> str:
        if not self.global_end: return "N/A"
        suffix = " (Predicted)" if self.global_is_predicted else ""
        return self.global_end.strftime('%Y-%m-%d') + suffix

    def matches_query(self, query: str) -> bool:
        query = query.lower()

        if query in ", ".join(self.units).lower():
            return True

        if query in self.start_str_asia.lower(): return True
        if query in self.end_str_asia.lower(): return True
        if query in self.start_str_global.lower(): return True
        if query in self.end_str_global.lower(): return True

        if query in self.asia_type.lower(): return True
        if query in self.global_type.lower(): return True

        return False


class BannerManager:
    def __init__(self):
        self.merged_banners: List[MergedBanner] = []
        self._time_offset: Optional[timedelta] = None

    def _fetch_html(self, url: str) -> str:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.text

    def _parse_banners(self, html: str, source: str) -> List[Banner]:
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("table.wikitable tr")[1:]
        banners: List[Banner] = []

        for row in rows:
            cols = row.select('td')
            if len(cols) < 3: continue

            release_type = row.get('data-release', 'unknown')

            img_tag = cols[0].find("img")
            img_url = "https:" + img_tag.get("src") if img_tag and img_tag.get("src") else "N/A"

            unit_cell = cols[1]
            units_list = [a.get_text(strip=True) for a in unit_cell.find_all("a") if a.get_text(strip=True)]

            rerun_tag = unit_cell.find('small')
            if rerun_tag and 'rerun' in rerun_tag.get_text(strip=True).lower():
                release_type = 'rerun'

            date_text = cols[2].get_text(strip=True)

            try:
                start_str, end_str = date_text.split("—")
                start = datetime.strptime(start_str.strip(), DATE_FORMAT)
                end = datetime.strptime(end_str.strip(), DATE_FORMAT)
            except Exception:
                continue

            banners.append(Banner(img_url, tuple(units_list), start, end, source, release_type))
        return banners

    def _calculate_offset(self, asia: List[Banner], global_list: List[Banner]):
        print("Calculating Asia-Global time offset...")
        if not global_list or not asia:
            print("Warning: Banner list(s) empty, cannot calculate offset.")
            return

        last_global_banner = max(global_list, key=lambda b: b.start)

        asia_match = None

        for b in reversed(asia):
            if b.matches_units(last_global_banner.units) and b.release_type == last_global_banner.release_type:
                asia_match = b
                break

        if not asia_match:
            print(
                f"Warning: Could not find exact type match for {last_global_banner.units}. Falling back to unit-only match.")
            for b in reversed(asia):
                if b.matches_units(last_global_banner.units):
                    asia_match = b
                    break

        if asia_match:
            self._time_offset = last_global_banner.start - asia_match.start
            print(f"✅ Time offset calculated: {self._time_offset.days} days (based on {asia_match.units})")
        else:
            print(f"❌ Could not find *any* match for {last_global_banner.units}. Prediction unavailable.")

    def _merge_and_predict_data(self, asia: List[Banner], global_list: List[Banner]) -> List[MergedBanner]:
        print("Merging Asia and Global data...")

        final_list: List[MergedBanner] = []

        global_banners_copy = list(global_list)
        used_global_banners = set()

        # 1. Ітеруємо по кожній ПОДІЇ в Asia
        for b_asia in asia:
            merged = MergedBanner(
                units=b_asia.units,
                image_url=b_asia.image_url,
                asia_start=b_asia.start,
                asia_end=b_asia.end,
                asia_type=b_asia.release_type
            )

            # Шукаємо точну пару (персонаж + тип) на Global
            found_global_match = False
            for i, b_global in enumerate(global_banners_copy):
                if i in used_global_banners:
                    continue

                if b_asia.matches(b_global):
                    merged.global_start = b_global.start
                    merged.global_end = b_global.end
                    merged.global_type = b_global.release_type
                    used_global_banners.add(i)
                    found_global_match = True
                    break

            # Якщо точної пари не знайдено, пробуємо знайти пару (персонаж + інший тип)
            # Це для випадків як Hina (Asia 'rerun' -> Global 'new')
            if not found_global_match:
                for i, b_global in enumerate(global_banners_copy):
                    if i in used_global_banners:
                        continue

                    if b_asia.matches_units(b_global.units):
                        merged.global_start = b_global.start
                        merged.global_end = b_global.end
                        merged.global_type = b_global.release_type
                        used_global_banners.add(i)
                        found_global_match = True
                        break

            # Якщо пари взагалі не знайдено, прогнозуємо
            if not found_global_match and self._time_offset:
                merged.global_start = b_asia.start + self._time_offset
                merged.global_end = b_asia.end + self._time_offset
                merged.global_is_predicted = True
                merged.global_type = b_asia.release_type

            final_list.append(merged)

        # 2. Додаємо банери, які є ТІЛЬКИ на Global (напр. колаби)
        for i, b_global in enumerate(global_banners_copy):
            if i not in used_global_banners:
                final_list.append(MergedBanner(
                    units=b_global.units,
                    image_url=b_global.image_url,
                    global_start=b_global.start,
                    global_end=b_global.end,
                    global_type=b_global.release_type
                ))

        # 3. Сортуємо за датою Global (реальною або прогнозованою)
        def get_sort_date(banner: MergedBanner):
            return banner.global_start or banner.asia_start or datetime.min

        return sorted(final_list, key=get_sort_date, reverse=True)

    def load_data(self):
        print("🔄 Loading banner data...")
        try:
            asia_html = self._fetch_html(ASIA_URL)
            global_html = self._fetch_html(GLOBAL_URL)
        except requests.HTTPError as e:
            print(f"❌ HTTP Error loading data: {e}", file=sys.stderr)
            return

        asia_banners = self._parse_banners(asia_html, "Asia")
        global_banners = self._parse_banners(global_html, "Global")

        self._calculate_offset(asia_banners, global_banners)
        self.merged_banners = self._merge_and_predict_data(asia_banners, global_banners)
        print(f"✅ Data merged. {len(self.merged_banners)} unique banners found.\n")

    def get_filtered_banners(self, query: str) -> List[MergedBanner]:
        if not query:
            return self.merged_banners

        query_lower = query.lower()
        return [b for b in self.merged_banners if b.matches_query(query_lower)]
