"""Oracle Cloud HCM public Candidate Experience collector.

Oracle's documented REST resources include recruiting endpoints, but several
candidate/job-site resources are restricted to approved partners or internal
use. This adapter therefore uses the employer's public Candidate Experience
pages and JobPosting JSON-LD instead of authenticated HCM APIs.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from src.collectors.ats_common import absolute_url, extract_address, iter_job_postings, jsonld_objects
from src.collectors.company_sources import HTTP, JobSource


class OracleHCMSource(JobSource):
    def fetch_jobs(self):
        pages = self.config.get("pages") or []
        if not isinstance(pages, list) or not pages:
            raise ValueError("Oracle HCM source requires non-empty pages.")

        hosts = self.config.get("fetch_hosts") or []
        if not isinstance(hosts, list) or not hosts:
            raise ValueError("Oracle HCM source requires fetch_hosts.")

        client = HTTP(set(hosts))
        max_jobs = int(self.config.get("max_jobs", 200))
        jobs = []

        for page in pages:
            host = urlsplit(page).hostname
            if host not in set(hosts):
                raise ValueError("Oracle HCM page host is not in fetch_hosts.")
            html = client.text(page)
            soup = BeautifulSoup(html, "html.parser")

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

            # Some Oracle CE pages expose links but no JSON-LD. Keep explicit
            # job URLs configurable rather than crawling the site indiscriminately.
            for anchor in soup.find_all("a", href=True):
                if len(jobs) >= max_jobs:
                    break
                text = anchor.get_text(" ", strip=True)
                href = absolute_url(page, anchor.get("href"))
                if not text or not ("job" in href.lower() or "apply" in text.lower()):
                    continue
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
