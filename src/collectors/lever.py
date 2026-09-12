import re
from urllib.parse import urlencode

from src.collectors.company_sources import HTTP, JobSource


class LeverSource(JobSource):
    def fetch_jobs(self):
        site = self.config["site"]
        if not isinstance(site, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]+", site
        ):
            raise ValueError("Invalid Lever site token.")

        # Some employers use Lever's EU instance.
        host = (
            "api.eu.lever.co"
            if self.config.get("region") == "eu"
            else "api.lever.co"
        )
        client = HTTP({host})
        url = (
            f"https://{host}/v0/postings/{site}?"
            + urlencode({"mode": "json"})
        )
        payload = client.json(url)

        if not isinstance(payload, list):
            raise ValueError("Unexpected Lever response.")

        jobs = []
        for posting in payload:
            if not isinstance(posting, dict):
                raise ValueError("Unexpected Lever posting.")

            categories = posting.get("categories") or {}
            sections = [
                posting.get("descriptionPlain")
                or posting.get("description")
                or "",
                posting.get("additionalPlain")
                or posting.get("additional")
                or "",
            ]

            for section in posting.get("lists") or []:
                sections.extend([
                    section.get("text") or "",
                    section.get("content") or "",
                ])

            # Do not assume that createdAt is the public posting date.
            jobs.append({
                "source_id": posting.get("id"),
                "title": posting.get("text"),
                "description": "\n".join(sections),
                "location": categories.get("location") or "",
                "workplace": posting.get("workplaceType") or "",
                "application_url": (
                    posting.get("applyUrl") or posting.get("hostedUrl")
                ),
                "posted_date": None,
                "deadline": None,
            })

        return jobs
