"""HRMOS public career-page collector."""

from __future__ import annotations

from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from src.collectors.ats_common import absolute_url, extract_address, iter_job_postings, jsonld_objects
from src.collectors.company_sources import HTTP, JobSource


class HRMOSSource(JobSource):
    def fetch_jobs(self):
        pages = self.config.get("pages") or []
        if not isinstance(pages, list) or not pages:
            raise ValueError("HRMOS source requires non-empty pages.")
        hosts = self.config.get("fetch_hosts") or ["hrmos.co"]
        if not isinstance(hosts, list) or not hosts:
            raise ValueError("HRMOS fetch_hosts must be non-empty.")

        client = HTTP(set(hosts))
        max_jobs = int(self.config.get("max_jobs", 200))
        jobs = []

        for page in pages:
            if urlsplit(page).hostname not in set(hosts):
                raise ValueError("HRMOS page host is not in fetch_hosts.")
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

            # Fallback: explicit candidate/apply/job links on the page. This is
            # deliberately shallow; it does not recursively crawl the portal.
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                if len(jobs) >= max_jobs:
                    break
                href = absolute_url(page, anchor.get("href"))
                text = anchor.get_text(" ", strip=True)
                if not text:
                    continue
                if any(token in href.lower() for token in ["/jobs/", "/job/"]) and "apply" in text.lower():
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
