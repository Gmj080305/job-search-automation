"""Public iCIMS career-site collector.

The vendor's authenticated Profiles/Job Portal APIs are not appropriate for an
unauthenticated personal tool, so this adapter uses the public hosted portal:
list jobs, follow job detail pages, extract JobPosting JSON-LD, and locate the
candidate/apply URL from the same job page.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from src.collectors.ats_common import absolute_url, extract_address, iter_job_postings, jsonld_objects
from src.collectors.company_sources import HTTP, JobSource


class ICIMSSource(JobSource):
    def _search_url(self):
        value = self.config.get("search_url")
        if isinstance(value, str) and value.strip():
            return value.strip()

        careers_url = self.config.get("careers_url")
        if not isinstance(careers_url, str):
            raise ValueError("iCIMS source requires careers_url or search_url.")
        parsed = urlsplit(careers_url)
        return urlunsplit(("https", parsed.netloc, "/jobs/search", "ss=1", ""))

    def fetch_jobs(self):
        search_url = self._search_url()
        host = urlsplit(search_url).hostname
        if not host or not host.endswith(".icims.com"):
            raise ValueError("iCIMS search_url must use an icims.com host.")

        client = HTTP({host})
        max_jobs = int(self.config.get("max_jobs", 200))
        max_pages = int(self.config.get("max_pages", 10))
        jobs = []
        visited = set()
        current_url = search_url

        for _ in range(max_pages):
            html = client.text(current_url)
            soup = BeautifulSoup(html, "html.parser")
            links = []
            for anchor in soup.find_all("a", href=True):
                href = absolute_url(current_url, anchor.get("href"))
                if host != urlsplit(href).hostname:
                    continue
                path = urlsplit(href).path
                if re.search(r"/jobs/\d+/.+/(?:job|candidate)", path, re.I):
                    links.append(href)

            # Deduplicate detail pages and prefer /job over /candidate.
            detail_urls = []
            for link in links:
                detail = re.sub(r"/candidate/?$", "/job", link)
                if detail not in visited:
                    visited.add(detail)
                    detail_urls.append(detail)

            for detail_url in detail_urls:
                detail_html = client.text(detail_url)
                found = False
                for payload in jsonld_objects(detail_html):
                    for posting in iter_job_postings(payload):
                        location, city = extract_address(posting.get("jobLocation"))
                        apply_url = self._find_apply_url(detail_html, detail_url)
                        if not apply_url:
                            apply_url = posting.get("url") or detail_url
                        jobs.append({
                            "source_id": self._identifier(posting, detail_url),
                            "title": posting.get("title"),
                            "description": posting.get("description"),
                            "location": location,
                            "city": city,
                            "workplace": "remote" if posting.get("jobLocationType") else "",
                            "application_url": apply_url,
                            "posted_date": posting.get("datePosted"),
                            "deadline": posting.get("validThrough"),
                        })
                        found = True
                        break
                    if found:
                        break
                if len(jobs) >= max_jobs:
                    return jobs[:max_jobs]

            next_link = None
            for anchor in soup.find_all("a", href=True):
                text = anchor.get_text(" ", strip=True).lower()
                if text in {"next", "next page", ">"}:
                    candidate = absolute_url(current_url, anchor.get("href"))
                    if urlsplit(candidate).hostname == host:
                        next_link = candidate
                        break
            if not next_link or next_link == current_url:
                break
            current_url = next_link

        return jobs[:max_jobs]

    @staticmethod
    def _identifier(posting, url):
        identifier = posting.get("identifier")
        if isinstance(identifier, dict):
            identifier = identifier.get("value")
        return identifier or url

    @staticmethod
    def _find_apply_url(html, detail_url):
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            text = anchor.get_text(" ", strip=True).lower()
            href = absolute_url(detail_url, anchor.get("href"))
            if "apply" in text or "/candidate" in href.lower():
                return href
        return None
