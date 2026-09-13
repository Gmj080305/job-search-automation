"""SmartRecruiters public Posting API collector."""

from __future__ import annotations

from urllib.parse import urlencode

from src.collectors.company_sources import HTTP, JobSource


class SmartRecruitersSource(JobSource):
    def fetch_jobs(self):
        company = self.config.get("company_identifier")
        if not isinstance(company, str) or not company.strip():
            raise ValueError("SmartRecruiters source requires company_identifier.")

        client = HTTP({"api.smartrecruiters.com"})
        limit = int(self.config.get("page_size", 100))
        max_jobs = int(self.config.get("max_jobs", 5000))
        if not 1 <= limit <= 100:
            raise ValueError("SmartRecruiters page_size must be 1..100.")

        jobs = []
        offset = 0
        total = None

        while len(jobs) < max_jobs:
            params = {"offset": offset, "limit": limit, "destination": "PUBLIC"}
            query = urlencode(params)
            url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings?{query}"
            payload = client.json(url)
            if not isinstance(payload, dict):
                raise ValueError("Unexpected SmartRecruiters response.")
            if total is None and isinstance(payload.get("totalFound"), int):
                total = payload["totalFound"]

            postings = payload.get("content")
            if not isinstance(postings, list):
                raise ValueError("Unexpected SmartRecruiters response: 'content' must be a list.")
            if not postings:
                break

            for posting in postings:
                if not isinstance(posting, dict):
                    continue
                posting_id = posting.get("uuid") or posting.get("id")
                detail = client.json(
                    f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}"
                )
                if not isinstance(detail, dict):
                    detail = {}

                location = posting.get("location") or detail.get("location") or {}
                if isinstance(location, dict):
                    location_text = ", ".join(
                        str(v) for v in [
                            location.get("city"),
                            location.get("region"),
                            location.get("country"),
                        ] if v
                    )
                else:
                    location_text = str(location or "")

                workplace = "remote" if isinstance(location, dict) and location.get("remote") else ""
                jobs.append({
                    "source_id": posting_id,
                    "title": detail.get("name") or posting.get("name"),
                    "description": detail.get("jobAd").get("sections") if isinstance(detail.get("jobAd"), dict) else detail.get("description"),
                    "location": location_text,
                    "workplace": workplace,
                    "application_url": detail.get("applyUrl") or posting.get("ref") or "",
                    "posted_date": detail.get("releasedDate") or detail.get("createdOn") or None,
                    "deadline": detail.get("expirationDate") or None,
                })
                if len(jobs) >= max_jobs:
                    break

            offset += len(postings)
            if len(postings) < limit:
                break
            if isinstance(total, int) and offset >= total:
                break

        # Convert structured job-ad sections to text where necessary.
        for job in jobs:
            desc = job.get("description")
            if isinstance(desc, list):
                pieces = []
                for section in desc:
                    if not isinstance(section, dict):
                        continue
                    pieces.extend([
                        section.get("title") or "",
                        section.get("content") or section.get("text") or "",
                    ])
                job["description"] = "\n".join(pieces)

        return jobs
