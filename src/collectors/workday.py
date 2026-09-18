"""Public Workday CXS collector.

Workday public career sites expose a JSON CXS endpoint of the form:
POST https://<tenant>.wd<N>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs
with a JSON request body. Full job details are available from the matching
GET https://<tenant>.wd<N>.myworkdayjobs.com/wday/cxs/<tenant>/<site><externalPath>
endpoint, where <externalPath> is the value returned by the listing call and
already starts with "/job/...". That GET returns the HTML shell of the
careers SPA (not JSON) unless an "Accept: application/json" header is sent,
and its payload nests every field under a top-level "jobPostingInfo" object.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlsplit

from src.collectors.company_sources import HTTP, JobSource


class WorkdaySource(JobSource):
    def _parts(self):
        tenant = self.config.get("tenant")
        datacenter = self.config.get("datacenter")
        site = self.config.get("site")
        locale = self.config.get("locale", "en-US")

        if not all(isinstance(x, str) and x.strip() for x in [tenant, datacenter, site]):
            raise ValueError("Workday source requires tenant, datacenter and site.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", tenant):
            raise ValueError("Invalid Workday tenant.")
        if not re.fullmatch(r"wd\d+", datacenter):
            raise ValueError("Invalid Workday datacenter.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", site):
            raise ValueError("Invalid Workday site.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", locale):
            raise ValueError("Invalid Workday locale.")
        return tenant, datacenter, site, locale

    def _post_json(self, client: HTTP, url: str, payload: dict):
        # HTTP currently exposes a GET JSON helper. Use its validated host,
        # robots and session safeguards for the Workday POST as well.
        parsed = client._check_url(url)
        client._check_robots(url, parsed)
        time.sleep(max(0, client.delay - (time.monotonic() - client.last_request)))
        client.last_request = time.monotonic()
        response = client.session.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Workday localizes list-response strings (postedOn,
                # locationsText) per Accept-Language; pin it so results don't
                # vary with the machine's/proxy's default locale.
                "Accept-Language": "en-US",
            },
            timeout=(10, 40),
        )
        response.raise_for_status()
        return response.json()

    def fetch_jobs(self):
        tenant, datacenter, site, locale = self._parts()
        host = f"{tenant}.{datacenter}.myworkdayjobs.com"
        client = HTTP({host})
        endpoint = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        base = f"https://{host}/{locale}/{site}"

        page_size = int(self.config.get("page_size", 20))
        max_jobs = int(self.config.get("max_jobs", 500))
        if not 1 <= page_size <= 20:
            raise ValueError("Workday page_size must be between 1 and 20.")
        if not 1 <= max_jobs <= 5000:
            raise ValueError("Workday max_jobs must be between 1 and 5000.")

        search_text = str(self.config.get("search_text") or "")
        jobs = []
        offset = 0
        total = None

        while len(jobs) < max_jobs:
            payload = self._post_json(
                client,
                endpoint,
                {
                    "appliedFacets": self.config.get("applied_facets") or {},
                    "limit": page_size,
                    "offset": offset,
                    "searchText": search_text,
                },
            )
            if not isinstance(payload, dict):
                raise ValueError("Unexpected Workday response: expected object.")
            if total is None and isinstance(payload.get("total"), int):
                total = payload["total"]

            postings = payload.get("jobPostings")
            if not isinstance(postings, list):
                raise ValueError("Unexpected Workday response: 'jobPostings' must be a list.")
            if not postings:
                break

            for posting in postings:
                if not isinstance(posting, dict):
                    continue
                external_path = str(posting.get("externalPath") or "")
                if not external_path.startswith("/"):
                    continue

                # externalPath already begins with "/job/..."; do not prepend
                # another "/job" segment or the request 404s.
                detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{external_path}"
                try:
                    raw_detail = client.json(detail_url)
                except Exception:
                    # Listing data is still useful if a detail request is unavailable.
                    raw_detail = {}

                if not isinstance(raw_detail, dict):
                    raw_detail = {}

                # The real CXS detail payload nests everything under
                # jobPostingInfo (siblings: hiringOrganization, similarJobs).
                detail = raw_detail.get("jobPostingInfo")
                if not isinstance(detail, dict):
                    detail = {}

                description = detail.get("jobDescription") or detail.get("description") or ""
                location = (
                    detail.get("locationsText")
                    or posting.get("locationsText")
                    or detail.get("location")
                    or ""
                )
                workplace = (
                    detail.get("workplaceType")
                    or detail.get("remoteType")
                    or detail.get("workArrangement")
                    or ""
                )
                job_url = urljoin(base + "/", external_path.lstrip("/"))
                apply_suffix = str(self.config.get("apply_suffix", "/apply/applyManually"))
                if not apply_suffix.startswith("/"):
                    apply_suffix = "/" + apply_suffix
                application_url = job_url.rstrip("/") + apply_suffix

                bullet_fields = posting.get("bulletFields")
                fallback_id = (
                    bullet_fields[-1]
                    if isinstance(bullet_fields, list) and bullet_fields
                    else external_path
                )
                jobs.append({
                    "source_id": detail.get("jobReqId") or fallback_id,
                    "title": detail.get("title") or posting.get("title"),
                    "description": description,
                    "location": location,
                    "workplace": workplace,
                    "application_url": application_url,
                    "posted_date": None,
                    "deadline": detail.get("endDate") or None,
                })
                if len(jobs) >= max_jobs:
                    break

            offset += len(postings)
            if len(postings) < page_size:
                break
            if isinstance(total, int) and offset >= total:
                break

        return jobs
