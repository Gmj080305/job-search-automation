"""
Fixture-based tests that feed each collector payloads shaped like the real,
live APIs (verified against Greenhouse/Lever/SmartRecruiters official docs
and Workday's real CXS response shape) and assert on the resulting
normalized job dicts. No network is used -- HTTP.json/_post_json are
monkeypatched.

Run: python3 tests/test_collectors_live_shape.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collectors import greenhouse, lever, smartrecruiters, workday
from src.collectors.company_sources import HTTP, normalize
from src.matching.skills import Taxonomy

PASS = "PASS"
FAIL = "FAIL"
results = []


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and status == FAIL else ""))
    assert condition, f"{name}: {detail}"


class MP:
    """Minimal monkeypatch shim (avoids a pytest dependency for this script)."""
    def __init__(self):
        self._orig = {}

    def setattr(self, obj, name, value):
        self._orig[(obj, name)] = getattr(obj, name)
        setattr(obj, name, value)

    def undo(self):
        for (obj, name), value in self._orig.items():
            setattr(obj, name, value)
        self._orig.clear()


TAXONOMY = Taxonomy("config/keywords.yaml")


def test_workday_fixed():
    mp = MP()
    detail_urls = []

    def fake_post_json(self, client, url, payload):
        if payload["offset"] == 0:
            return {
                "total": 1,
                "jobPostings": [{
                    "title": "Hardware Engineer",
                    "externalPath": "/job/US-CA-Santa-Clara/Hardware-Engineer_JR1988177",
                    "locationsText": "Santa Clara, CA",
                    "postedOn": "Posted Today",
                    "bulletFields": ["JR1988177"],
                }],
            }
        return {"total": 1, "jobPostings": []}

    def fake_json(self, url):
        detail_urls.append(url)
        return {
            "jobPostingInfo": {
                "title": "Hardware Engineer",
                "jobDescription": (
                    "Entry level position. Freshers welcome. Onsite role in "
                    "Santa Clara. Electronics engineering degree required. "
                    "RTL and Verilog experience is a plus."
                ),
                "jobReqId": "JR1988177",
                "locationsText": "Santa Clara, CA",
                "workplaceType": "On-Site",
                "endDate": None,
            },
            "hiringOrganization": {},
            "similarJobs": [],
        }

    mp.setattr(workday.WorkdaySource, "_post_json", fake_post_json)
    mp.setattr(HTTP, "json", fake_json)
    try:
        source = workday.WorkdaySource({
            "tenant": "nvidia", "datacenter": "wd5", "site": "NVIDIAExternalCareerSite",
            "max_jobs": 10,
        })
        jobs = source.fetch_jobs()
        check("workday: fetch returns one job", len(jobs) == 1, f"got {len(jobs)}")
        job = jobs[0]

        check(
            "workday: detail URL has no double /job/job/",
            bool(detail_urls) and "/job/job/" not in detail_urls[0],
            detail_urls[0] if detail_urls else "no request made",
        )
        check(
            "workday: description is populated from jobPostingInfo",
            "Onsite role in Santa Clara" in job["description"],
            repr(job["description"])[:100],
        )
        check(
            "workday: workplace picked up from workplaceType",
            job["workplace"] == "On-Site",
            repr(job["workplace"]),
        )
        check(
            "workday: source_id uses jobReqId",
            job["source_id"] == "JR1988177",
            repr(job["source_id"]),
        )

        # Full normalize() + eligibility pass -- this is the thing that was
        # silently rejecting every Workday job before the fix.
        config = {
            "name": "NVIDIA",
            "application_prefixes": [
                "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/"
            ],
        }
        job["application_url"] = (
            "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"
            "/job/US-CA-Santa-Clara/Hardware-Engineer_JR1988177/apply/applyManually"
        )
        normalized = normalize(config, job, TAXONOMY)
        check(
            "workday: normalize() picks up work_mode=onsite",
            normalized["work_mode"] == "onsite",
            repr(normalized["work_mode"]),
        )
        check(
            "workday: normalize() extracts skills from real description",
            {"RTL", "Verilog"} <= set(normalized["skills"]),
            repr(normalized["skills"]),
        )
    finally:
        mp.undo()


def test_smartrecruiters_fixed():
    mp = MP()

    def fake_json(self, url):
        if url.endswith("/postings?offset=0&limit=100&destination=PUBLIC"):
            return {"totalFound": 1, "content": [{"uuid": "abc123", "name": "Analog IC Design Engineer"}]}
        if "offset=100" in url:
            return {"totalFound": 1, "content": []}
        if url.endswith("/postings/abc123"):
            return {
                "id": "abc123",
                "name": "Analog IC Design Engineer",
                "applyUrl": "https://jobs.smartrecruiters.com/oneclick-ui/company/RenesasElectronics/publication/abc123",
                "location": {"city": "Bangalore", "region": "KA", "country": "India", "remote": False, "hybrid": False},
                "jobAd": {
                    "sections": {
                        "companyDescription": {"title": "Company Description", "text": "Renesas is a global semiconductor company."},
                        "jobDescription": {"title": "Job Description", "text": "Entry level position. Freshers welcome. Onsite role in Bangalore."},
                        "qualifications": {"title": "Qualifications", "text": "BE/BTech in ECE. Verilog knowledge required."},
                    }
                },
            }
        raise AssertionError(f"unexpected url {url}")

    mp.setattr(HTTP, "json", fake_json)
    try:
        source = smartrecruiters.SmartRecruitersSource({"company_identifier": "RenesasElectronics", "max_jobs": 10})
        jobs = source.fetch_jobs()
        check("smartrecruiters: fetch returns one job", len(jobs) == 1, f"got {len(jobs)}")
        job = jobs[0]

        check(
            "smartrecruiters: description is a clean string, not a dict",
            isinstance(job["description"], str) and "Verilog knowledge required" in job["description"],
            repr(job["description"])[:120],
        )
        check(
            "smartrecruiters: workplace left blank (remote=False, hybrid=False)",
            job["workplace"] == "",
            repr(job["workplace"]),
        )

        config = {
            "name": "Renesas",
            "application_prefixes": [
                "https://jobs.smartrecruiters.com/oneclick-ui/company/RenesasElectronics/"
            ],
        }
        normalized = normalize(config, job, TAXONOMY)
        check(
            "smartrecruiters: normalize() extracts skills from real description",
            "Verilog" in normalized["skills"],
            repr(normalized["skills"]),
        )
        check(
            "smartrecruiters: normalize() extracts India from location",
            normalized["country"] == "India",
            repr(normalized["country"]),
        )
    finally:
        mp.undo()


def test_greenhouse_regression():
    mp = MP()

    def fake_json(self, url):
        # Real Greenhouse /v1/boards/{token}/jobs?content=true shape.
        return {
            "jobs": [{
                "id": 555,
                "title": "FPGA Design Intern",
                "content": "<p>Internship. Entry level. This is an onsite role based in Bengaluru. FPGA and Verilog required.</p>",
                "location": {"name": "Bengaluru, India"},
                "absolute_url": "https://job-boards.greenhouse.io/example/jobs/555",
            }],
        }

    mp.setattr(HTTP, "json", fake_json)
    try:
        source = greenhouse.GreenhouseSource({"board": "example"})
        jobs = source.fetch_jobs()
        check("greenhouse: fetch returns one job", len(jobs) == 1, f"got {len(jobs)}")
        job = jobs[0]
        config = {"name": "Example", "application_prefixes": ["https://job-boards.greenhouse.io/example/jobs/"]}
        normalized = normalize(config, job, TAXONOMY)
        check("greenhouse: title carried through", normalized["title"] == "FPGA Design Intern")
        check("greenhouse: work_mode=onsite", normalized["work_mode"] == "onsite", repr(normalized["work_mode"]))
        check("greenhouse: country=India", normalized["country"] == "India", repr(normalized["country"]))
    finally:
        mp.undo()


def test_lever_regression():
    mp = MP()

    def fake_json(self, url):
        # Real Lever /v0/postings/{site}?mode=json shape.
        return [{
            "id": "post-1",
            "text": "RF Engineer, New Grad",
            "descriptionPlain": "New graduate role. Onsite. RF and wireless systems work.",
            "categories": {"location": "Tokyo, Japan"},
            "workplaceType": "on-site",
            "applyUrl": "https://jobs.lever.co/example/post-1/apply",
            "hostedUrl": "https://jobs.lever.co/example/post-1",
        }]

    mp.setattr(HTTP, "json", fake_json)
    try:
        source = lever.LeverSource({"site": "example"})
        jobs = source.fetch_jobs()
        check("lever: fetch returns one job", len(jobs) == 1, f"got {len(jobs)}")
        job = jobs[0]
        config = {"name": "Example", "application_prefixes": ["https://jobs.lever.co/example/"]}
        normalized = normalize(config, job, TAXONOMY)
        check("lever: work_mode=onsite", normalized["work_mode"] == "onsite", repr(normalized["work_mode"]))
        check("lever: country=Japan", normalized["country"] == "Japan", repr(normalized["country"]))
    finally:
        mp.undo()


if __name__ == "__main__":
    test_workday_fixed()
    test_smartrecruiters_fixed()
    test_greenhouse_regression()
    test_lever_regression()

    failed = [r for r in results if r[1] == FAIL]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    if failed:
        print("FAILURES:")
        for name, _, detail in failed:
            print(f"  - {name}: {detail}")
        sys.exit(1)
