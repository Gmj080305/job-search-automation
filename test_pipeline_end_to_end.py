"""
End-to-end dry run of the real pipeline (collect -> screen -> rank -> tips)
against every currently-enabled source in config/companies.yaml, with the
network layer mocked using realistic per-platform fixtures. Proves the fixed
collectors flow through eligibility screening and produce ranked output.

Run: python3 tests/test_pipeline_end_to_end.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collectors import icims, smartrecruiters, workday
from src.collectors.company_sources import HTTP
from src.main import collect, process
from src.matching.skills import Taxonomy
from src.resume.parser import profile_from_text


RESUME_TEXT = """
Jane Doe
B.Tech, Electronics and Communication Engineering, 2026
Currently pursuing undergraduate student.

Projects
FPGA-based UART controller in Verilog with AXI interconnect.
RF front-end design for a wireless communication testbed.

Skills
Verilog, RTL, FPGA, AXI, RF, Wireless, Python, C++
"""


def fake_workday_post_json(self, client, url, payload):
    if payload["offset"] != 0:
        return {"total": 1, "jobPostings": []}
    tenant = url.split("/wday/cxs/")[1].split("/")[0]
    return {
        "total": 1,
        "jobPostings": [{
            "title": "New Grad Hardware Engineer",
            "externalPath": f"/job/Loc/{tenant}-Hardware-Engineer_JR001",
            "locationsText": "Bengaluru, India" if tenant != "sonyglobal" else "Tokyo, Japan",
            "postedOn": "Posted Today",
            "bulletFields": ["JR001"],
        }],
    }


def fake_http_json(self, url):
    if "/wday/cxs/" in url:
        return {
            "jobPostingInfo": {
                "title": "New Grad Hardware Engineer",
                "jobDescription": (
                    "New graduate role. Onsite position in our design center. "
                    "Work on RTL, Verilog and FPGA-based verification using AXI. "
                    "Freshers welcome; no prior experience required."
                ),
                "jobReqId": "JR001",
                "locationsText": "Bengaluru, India",
                "workplaceType": "On-Site",
                "endDate": None,
            },
        }
    if "smartrecruiters" in url and url.endswith("destination=PUBLIC"):
        return {"totalFound": 1, "content": [{"uuid": "sr1", "name": "RF Engineer, New Grad"}]}
    if "smartrecruiters" in url and "offset=100" in url:
        return {"totalFound": 1, "content": []}
    if "smartrecruiters" in url and url.endswith("/postings/sr1"):
        return {
            "id": "sr1",
            "name": "RF Engineer, New Grad",
            "applyUrl": "https://jobs.smartrecruiters.com/oneclick-ui/company/RenesasElectronics/publication/sr1",
            "location": {"city": "Bengaluru", "region": "KA", "country": "India", "remote": False, "hybrid": False},
            "jobAd": {"sections": {
                "jobDescription": {"title": "Job Description", "text": (
                    "Entry level position, onsite role in Bengaluru. Freshers welcome. "
                    "RF and wireless systems work using Verilog-based test benches."
                )},
            }},
        }
    raise AssertionError(f"unexpected JSON url: {url}")


def fake_icims_text(self, url):
    # Simulate one search results page with one job link, and its detail page.
    if url.endswith("/jobs/search?ss=1"):
        return (
            '<html><body>'
            '<a href="/jobs/501/hardware-test-engineer/job">Hardware Test Engineer</a>'
            '</body></html>'
        )
    if url.endswith("/jobs/501/hardware-test-engineer/job"):
        return (
            '<html><body>'
            '<script type="application/ld+json">'
            '{"@type": "JobPosting", "title": "Hardware Test Engineer", '
            '"description": "New graduate, entry level, onsite role in Bengaluru, India. '
            'Embedded C and hardware validation. Freshers welcome.", '
            '"jobLocation": {"address": {"addressLocality": "Bengaluru", "addressCountry": "India"}}}'
            '</script>'
            '<a href="/jobs/501/hardware-test-engineer/apply">Apply Now</a>'
            '</body></html>'
        )
    raise AssertionError(f"unexpected text url: {url}")


def run():
    import types
    class MP:
        def __init__(self):
            self._orig = {}
        def setattr(self, obj, name, value):
            self._orig[(obj, name)] = getattr(obj, name)
            setattr(obj, name, value)
        def undo(self):
            for (obj, name), value in self._orig.items():
                setattr(obj, name, value)

    mp = MP()
    mp.setattr(workday.WorkdaySource, "_post_json", fake_workday_post_json)
    mp.setattr(HTTP, "json", fake_http_json)
    mp.setattr(HTTP, "text", fake_icims_text)

    try:
        args = types.SimpleNamespace(
            companies="config/companies.yaml",
            keywords="config/keywords.yaml",
        )
        jobs, collection_stats = collect(args)
        print("=== collection stats ===")
        for s in collection_stats["sources"]:
            print(f"  {s['company']:12s} status={s['status']:6s} fetched={s.get('fetched',0)} "
                  f"accepted={s.get('accepted',0)} error={s.get('error','')}")
        print(f"total collected: {collection_stats['collected_jobs']}")

        taxonomy = Taxonomy("config/keywords.yaml")
        profile = profile_from_text(RESUME_TEXT, taxonomy)

        import yaml
        with open("config/scoring.yaml", encoding="utf-8") as f:
            settings = yaml.safe_load(f)

        ranked, processing_stats = process(jobs, profile, taxonomy, settings)
        print("\n=== processing stats ===")
        print(processing_stats)
        print(f"\neligible/ranked jobs: {len(ranked)}")
        for job in ranked:
            print(f"  - [{job['application_priority']}] {job['company']}: {job['title']} "
                  f"(score={job['match_score']}, work_mode={job['work_mode']})")

        assert collection_stats["collected_jobs"] > 0, "collector-level bug: still collecting zero raw jobs"
        assert len(ranked) > 0, "eligibility-level bug: jobs collected but all screened out"
        print("\nEND-TO-END PIPELINE: PASS (non-zero listings reach the ranked output)")
    finally:
        mp.undo()


if __name__ == "__main__":
    run()
