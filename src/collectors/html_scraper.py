import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.collectors.company_sources import HTTP, JobSource


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def job_postings(value):
    """Find JobPosting objects, including those inside @graph."""
    if isinstance(value, list):
        for item in value:
            yield from job_postings(item)
    elif isinstance(value, dict):
        types = as_list(value.get("@type"))
        if any(
            str(item).rstrip("/").split("/")[-1] == "JobPosting"
            for item in types
        ):
            yield value
        else:
            for child in value.values():
                if isinstance(child, (dict, list)):
                    yield from job_postings(child)


def named(value):
    if isinstance(value, dict):
        return value.get("name") or value.get("@id") or ""
    return str(value or "")


class HTMLCareerSource(JobSource):
    """Read explicit pages only; no crawling or browser automation."""

    def fetch_jobs(self):
        pages = self.config.get("pages")
        hosts = self.config.get("fetch_hosts")

        if not isinstance(pages, list) or not pages:
            raise ValueError("HTML source requires non-empty pages.")
        if not isinstance(hosts, list) or not hosts:
            raise ValueError("HTML source requires fetch_hosts.")

        client = HTTP(hosts)
        jobs = []

        for page in pages:
            soup = BeautifulSoup(client.text(page), "html.parser")

            for script in soup.find_all(
                "script", attrs={"type": "application/ld+json"}
            ):
                # Invalid structured data invalidates this source run rather
                # than silently producing an apparently complete result.
                payload = json.loads(script.get_text())

                for posting in job_postings(payload):
                    identifier = posting.get("identifier")
                    if isinstance(identifier, dict):
                        identifier = identifier.get("value")
                    if not isinstance(identifier, (str, int)):
                        identifier = None

                    application_url = posting.get("url") or page
                    if not isinstance(application_url, str):
                        raise ValueError("JobPosting URL must be a string.")
                    application_url = urljoin(page, application_url)

                    workplace = ""
                    if any(
                        str(value).upper() == "TELECOMMUTE"
                        for value in as_list(
                            posting.get("jobLocationType")
                        )
                    ):
                        workplace = "remote"

                    locations = as_list(posting.get("jobLocation")) or [{}]

                    for place in locations:
                        address = (
                            place.get("address", {})
                            if isinstance(place, dict)
                            else {}
                        )

                        if isinstance(address, str):
                            location = address
                            city = None
                        elif isinstance(address, dict):
                            city = named(address.get("addressLocality"))
                            location = ", ".join(filter(None, [
                                city,
                                named(address.get("addressRegion")),
                                named(address.get("addressCountry")),
                            ]))
                        else:
                            location, city = "", None

                        jobs.append({
                            "source_id": identifier,
                            "title": posting.get("title"),
                            "description": posting.get("description"),
                            "location": location,
                            "city": city,
                            "workplace": workplace,
                            "application_url": application_url,
                            "posted_date": posting.get("datePosted"),
                            "deadline": posting.get("validThrough"),
                        })

        return jobs
