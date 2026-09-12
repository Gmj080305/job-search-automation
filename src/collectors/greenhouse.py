import re

from src.collectors.company_sources import HTTP, JobSource


class GreenhouseSource(JobSource):
    """Fetch public job records from a configured Greenhouse board."""

    def fetch_jobs(self):
        board = self.config.get("board")

        if (
            not isinstance(board, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", board)
        ):
            raise ValueError("Invalid or missing Greenhouse board token.")

        client = HTTP({"boards-api.greenhouse.io"})
        url = (
            f"https://boards-api.greenhouse.io/v1/boards/{board}"
            "/jobs?content=true"
        )

        # Let HTTP/network errors propagate so the pipeline can report
        # a source failure instead of treating it as an empty job board.
        payload = client.json(url)
        if not isinstance(payload, dict):
            raise ValueError(
                "Unexpected Greenhouse response: expected a JSON object."
            )

        jobs = payload.get("jobs")

        if not isinstance(jobs, list):
            raise ValueError(
                "Unexpected Greenhouse response: 'jobs' must be a list."
            )
        if any(not isinstance(job, dict) for job in jobs):
            raise ValueError(
                "Unexpected Greenhouse response: each job must be an object."
            )

        postings = []

        for job in jobs:
            location = job.get("location")
            if location is None:
                location_name = ""
            elif isinstance(location, dict):
                location_name = location.get("name") or ""
                if not isinstance(location_name, str):
                    raise ValueError("Unexpected Greenhouse location name.")
            else:
                raise ValueError(
                    "Unexpected Greenhouse location: expected an object."
                )

            postings.append({
                "source_id": job.get("id"),
                "title": job.get("title"),
                "description": job.get("content"),
                "location": location_name,
                "application_url": job.get("absolute_url"),
                # Leave unsupported facts unknown.
                "city": None,
                "workplace": None,
                "posted_date": None,
                "deadline": None,
            })

        return postings
