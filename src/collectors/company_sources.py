import hashlib
import re
import time
from abc import ABC, abstractmethod
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from src.matching.skills import contains


def plain(value):
    return BeautifulSoup(str(value or ""), "html.parser").get_text(
        " ", strip=True
    )


def official_url(url, prefixes):
    try:
        target = urlsplit(url)
        if (
            target.scheme != "https"
            or not target.hostname
            or target.username
            or target.password
            or target.port not in (None, 443)
        ):
            return False

        for prefix in prefixes:
            allowed = urlsplit(prefix)
            if (
                allowed.scheme != "https"
                or allowed.username
                or allowed.password
                or allowed.port not in (None, 443)
                or allowed.hostname != target.hostname
            ):
                continue

            base = allowed.path.rstrip("/")
            if (
                not base
                or target.path == base
                or target.path.startswith(base + "/")
            ):
                return True
    except (TypeError, ValueError):
        pass
    return False


class HTTP:
    """Bounded requests, host restrictions, robots checks and pacing."""

    def __init__(self, hosts, delay=1.5):
        self.hosts = set(hosts)
        self.delay = delay
        self.last_request = 0.0
        self.robots = {}
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "ECEJobFinder/1.0"

    def _check_url(self, url):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self.hosts
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Request URL is outside configured HTTPS hosts.")
        return parsed

    def _request(self, url, check_robots=True, headers=None):
        for _ in range(6):
            parsed = self._check_url(url)
            if check_robots:
                self._check_robots(url, parsed)

            time.sleep(max(
                0,
                self.delay - (time.monotonic() - self.last_request),
            ))
            self.last_request = time.monotonic()

            with self.session.get(
                url,
                timeout=(10, 40),
                allow_redirects=False,
                stream=True,
                headers=headers,
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers["Location"])
                    continue

                if not check_robots and response.status_code == 404:
                    return ""

                response.raise_for_status()

                body = bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > 12_000_000:
                        raise ValueError("Response exceeds 12 MB limit.")

                return bytes(body).decode("utf-8", errors="replace")

        raise ValueError("Too many redirects.")

    def _check_robots(self, url, parsed):
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.robots:
            text = self._request(
                origin + "/robots.txt",
                check_robots=False,
            )
            rules = RobotFileParser()
            rules.parse(text.splitlines())
            self.robots[origin] = rules

        rules = self.robots[origin]
        agent = "ECEJobFinder"

        if not rules.can_fetch(agent, url):
            raise ValueError("Collection disallowed by robots.txt.")

        crawl_delay = rules.crawl_delay(agent)
        request_rate = rules.request_rate(agent)
        if crawl_delay:
            self.delay = max(self.delay, crawl_delay)
        if request_rate and request_rate.requests:
            self.delay = max(
                self.delay,
                request_rate.seconds / request_rate.requests,
            )

    def text(self, url):
        return self._request(url)

    def json(self, url):
        import json
        # Some ATS platforms (notably Workday's CXS detail endpoint) serve the
        # careers page's HTML shell on this exact URL unless JSON is
        # explicitly requested. Without this header, json.loads() would raise
        # on the HTML body, which upstream code may treat as "no data".
        return json.loads(
            self._request(url, headers={"Accept": "application/json"})
        )


def country_from_location(location):
    countries = []
    for country, terms in {
        "India": ["India", "IN"],
        "Japan": ["Japan", "JP", "日本"],
    }.items():
        if any(contains(location, term) for term in terms):
            countries.append(country)
    return countries[0] if len(countries) == 1 else None


def normalize(config, raw, taxonomy):
    application_url = str(raw.get("application_url") or "")
    if not official_url(
        application_url,
        config.get("application_prefixes", []),
    ):
        raise ValueError("Application URL is outside verified prefixes.")

    title = plain(raw.get("title"))
    description = plain(raw.get("description"))
    location = plain(raw.get("location"))
    text = f"{title}\n{description}"
    workplace = plain(raw.get("workplace"))

    if not title:
        raise ValueError("Posting has no title.")

    work_mode = None
    if contains(workplace, "hybrid"):
        work_mode = "hybrid"
    elif contains(workplace, "remote"):
        work_mode = "remote"
    elif any(contains(workplace, x) for x in ["onsite", "on-site", "on site"]):
        work_mode = "onsite"
    else:
        # Require explicit workplace language, not unrelated "remote" mentions.
        if re.search(r"\b(?:work mode|workplace type|work arrangement)"
                     r"\s*:\s*hybrid\b", text, re.I):
            work_mode = "hybrid"
        elif re.search(r"\b(?:fully remote|remote position|remote role)\b",
                       text, re.I):
            work_mode = "remote"
        elif re.search(r"\b(?:on[- ]?site position|on[- ]?site role|"
                       r"work on[- ]?site)\b", text, re.I):
            work_mode = "onsite"

    employment = "unknown"
    if re.search(r"\bintern(?:ship)?\b", title, re.I):
        employment = "internship"
    elif re.search(r"\b(?:new grad(?:uate)?|graduate|fresher)\b",
                   title, re.I):
        employment = "new_graduate"

    degrees = []
    if any(contains(description, term) for term in [
        "ECE", "electronics and communication",
        "electronics & communication",
    ]):
        degrees.append("ECE")
    if any(contains(description, term) for term in [
        "EE", "electrical engineering",
    ]):
        degrees.append("EE")
    if contains(description, "electronics engineering"):
        degrees.append("Electronics")

    source_key = config["name"].strip().casefold()
    identity = raw.get("source_id") or application_url
    digest = hashlib.sha256(
        f"{source_key}|{identity}|{location.casefold()}".encode()
    ).hexdigest()[:24]

    return {
        "id": digest,
        "company": config["name"],
        "title": title,
        "country": country_from_location(location),
        "city": plain(raw.get("city")) or None,
        "location": location,
        "work_mode": work_mode,
        "employment": employment,
        "degree": sorted(set(degrees)),
        "skills": sorted(taxonomy.extract(text)),
        "description": description,
        "application_url": application_url,
        "source_url": application_url,
        "posted_date": raw.get("posted_date"),
        "deadline": raw.get("deadline"),
        # Unknown is not false. Generic adapters do not infer these fields.
        "japanese_required": None,
        "english_required": None,
        "international_applicant": None,
        "visa_support": None,
    }


class JobSource(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def fetch_jobs(self):
        """Return raw postings; adapter failures invalidate this source run."""
        raise NotImplementedError
