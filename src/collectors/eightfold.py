"""Conservative collector for Eightfold-powered employer career sites.

Eightfold career sites are dynamic and tenant-specific. Rather than depending
on an undocumented tenant API, this adapter reads the employer's public career
page and any explicit JobPosting JSON-LD it exposes. Optional `pages` can list
known public search/result pages. The adapter is intentionally non-crawling.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from src.collectors.ats_common import absolute_url, extract_address, iter_job_postings, jsonld_objects
from src.collectors.company_sources import HTTP, JobSource


class EightfoldSource(JobSource):
    def fetch_jobs(self):
        pages = self.config.get("pages") or [self.config.get("careers_url")]
        pages = [p for p in pages if isinstance(p, str) and p.strip()]
        if not pages:
            raise ValueError("Eightfold source requires careers_url or pages.")

        hosts = self.config.get("fetch_hosts") or []
        if not hosts:
            hosts = sorted({urlsplit(page).hostname for page in pages if urlsplit(page).hostname})
        hosts = [h for h in hosts if isinstance(h, str) and h]
        if not hosts:
            raise ValueError("Eightfold source could not determine fetch_hosts.")

        client = HTTP(set(hosts))
        max_jobs = int(self.config.get("max_jobs", 200))
        jobs = []

        for page in pages:
            host = urlsplit(page).hostname
            if host not in set(hosts):
                raise ValueError("Eightfold page host is not in fetch_hosts.")
            html = client.text(page)

            for payload in jsonld_objects(html):
                for posting in iter_job_postings(payload):
                    location, city = extract_address(posting.get("jobLocation"))
                    application_url = absolute_url(page, posting.get("url") or page)
                    jobs.append({
                        "source_id": self._identifier(posting, application_url),
                        "title": posting.get("title"),
                        "description": posting.get("description"),
                        "location": location,
                        "city": city,
                        "workplace": "remote" if posting.get("jobLocationType") else "",
                        "application_url": application_url,
                        "posted_date": posting.get("datePosted"),
                        "deadline": posting.get("validThrough"),
                    })
                    if len(jobs) >= max_jobs:
                        return jobs[:max_jobs]

            # Capture explicit job links without recursively crawling them.
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                if len(jobs) >= max_jobs:
                    break
                href = absolute_url(page, anchor.get("href"))
                text = anchor.get_text(" ", strip=True)
                if not text or urlsplit(href).hostname != host:
                    continue
                if any(token in href.lower() for token in ["/job/", "/jobs/"]) and href not in {j.get("application_url") for j in jobs}:
                    jobs.append({
                        "source_id": href,
                        "title": text,
                        "description": "",
                        "location": "",
                        "workplace": "",
                        "application_url": href,
                        "posted_date": None,
                        "deadline": None,
                    })

        return jobs[:max_jobs]

    @staticmethod
    def _identifier(posting, fallback):
        identifier = posting.get("identifier")
        if isinstance(identifier, dict):
            identifier = identifier.get("value")
        return identifier or fallback
