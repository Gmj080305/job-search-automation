"""SmartRecruiters public Posting API collector."""

from __future__ import annotations

from urllib.parse import urlencode

from src.collectors.company_sources import HTTP, JobSource

# Order mirrors SmartRecruiters' documented JobAd.sections object. Each
# section (when present) is {"title": str, "text": str}; "videos" is excluded
# since it carries "urls", not "text".
_JOBAD_SECTION_ORDER = (
    "jobDescription",
    "qualifications",
    "additionalInformation",
    "companyDescription",
)


def _jobad_text(detail):
    """Flatten SmartRecruiters' PostingDetails.jobAd.sections object to text.

    The real API shape (per SmartRecruiters' published Posting API docs) is::

        {"jobAd": {"sections": {
            "jobDescription": {"title": "...", "text": "..."},
            "qualifications": {"title": "...", "text": "..."},
            ...
        }}}

    i.e. ``sections`` is a dict keyed by section name, not a list.
    """
    job_ad = detail.get("jobAd")
    sections = job_ad.get("sections") if isinstance(job_ad, dict) else None
    if not isinstance(sections, dict):
        return str(detail.get("description") or "")

    pieces = []
    for key in _JOBAD_SECTION_ORDER:
        section = sections.get(key)
        if not isinstance(section, dict):
            continue
        title = section.get("title") or ""
        text = section.get("text") or ""
        if title or text:
            pieces.extend([title, text])
    return "\n".join(p for p in pieces if p)


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

                workplace = ""
                if isinstance(location, dict):
                    if location.get("remote"):
                        workplace = "remote"
                    elif location.get("hybrid"):
                        workplace = "hybrid"

                jobs.append({
                    "source_id": posting_id,
                    "title": detail.get("name") or posting.get("name"),
                    "description": _jobad_text(detail),
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

        return jobs
