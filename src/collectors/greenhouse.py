import re

from src.collectors.company_sources import HTTP, JobSource


class GreenhouseSource(JobSource):
    def fetch_jobs(self):
        board = self.config["board"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", board):
            raise ValueError("Invalid Greenhouse board token.")

        client = HTTP({"boards-api.greenhouse.io"})
        url = (
            f"https://boards-api.greenhouse.io/v1/boards/{board}"
            "/jobs?content=true"
        )
        payload = client.json(url)

        if not isinstance(payload.get("jobs"), list):
            raise ValueError("Unexpected Greenhouse
