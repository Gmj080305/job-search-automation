"""Job-search automation pipeline entry point.

Run from the repository root with either:
    python -m src.main --resume path/to/resume.pdf
or:
    python src/main.py --resume path/to/resume.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Any

# Make direct `python src/main.py ...` work as well as `python -m src.main ...`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from src.collectors.company_sources import normalize
from src.matching.eligibility import evaluate
from src.matching.ranking import rank_job, sort_jobs, validate_settings
from src.matching.skills import Taxonomy
from src.resume.parser import parse_pdf
from src.tips.generator import generate_tips


ADAPTERS = {
    "greenhouse": ("src.collectors.greenhouse", "GreenhouseSource"),
    "lever": ("src.collectors.lever", "LeverSource"),
    "html": ("src.collectors.html_scraper", "HTMLCareerSource"),
    "workday": ("src.collectors.workday", "WorkdaySource"),
    "icims": ("src.collectors.icims", "ICIMSSource"),
    "smartrecruiters": ("src.collectors.smartrecruiters", "SmartRecruitersSource"),
    "oracle_hcm": ("src.collectors.oracle_hcm", "OracleHCMSource"),
    "hrmos": ("src.collectors.hrmos", "HRMOSSource"),
    "eightfold": ("src.collectors.eightfold", "EightfoldSource"),
}

PUBLIC_FIELDS = (
    "id",
    "company",
    "title",
    "country",
    "city",
    "location",
    "work_mode",
    "employment",
    "degree",
    "skills",
    "description",
    "application_url",
    "source_url",
    "posted_date",
    "deadline",
    "japanese_required",
    "english_required",
    "international_applicant",
    "visa_support",
    "match_score",
    "application_priority",
    "priority_score",
    "priority_reasons",
    "matches",
    "score_breakdown",
    "screening",
    "tips",
    "project_matches",
)


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    return value if isinstance(value, dict) else {}


def load_json(path: str | Path) -> Any:
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: str | Path, value: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(destination)


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise ValueError("Candidate profile must be a JSON object.")

    for field in ("skills", "projects"):
        if not isinstance(profile.get(field), list) or not all(
            isinstance(value, str) for value in profile[field]
        ):
            raise ValueError(f"Profile {field} must be a list of strings.")

    countries = profile.get("preferred_countries", ["India", "Japan"])
    if not isinstance(countries, list) or not all(
        isinstance(country, str) for country in countries
    ):
        raise ValueError("preferred_countries must be a list of strings.")

    profile["preferred_countries"] = countries
    return profile


def _build_source(config: dict[str, Any]):
    adapter = config.get("adapter")
    if adapter not in ADAPTERS:
        raise ValueError(
            f"Unsupported adapter for {config.get('name', '<unnamed>')}: {adapter!r}."
        )

    module_name, class_name = ADAPTERS[adapter]
    module = import_module(module_name)
    source_class = getattr(module, class_name)
    return source_class(config)


def _validate_source_config(config: dict[str, Any]) -> None:
    name = str(config.get("name") or "<unnamed>")
    if not config.get("enabled", False):
        return
    if config.get("verified") is not True:
        raise ValueError(f"Enabled source {name} must have verified: true.")

    careers_url = config.get("careers_url")
    prefixes = config.get("application_prefixes")
    if not isinstance(careers_url, str) or not careers_url:
        raise ValueError(f"Enabled source {name} is missing careers_url.")
    if not isinstance(prefixes, list) or not prefixes:
        raise ValueError(f"Enabled source {name} is missing application_prefixes.")
    if not all(isinstance(prefix, str) and prefix.strip() for prefix in prefixes):
        raise ValueError(f"application_prefixes for {name} must be non-empty strings.")

    # careers_url is the official employer career page and may legitimately
    # use a different host from the ATS/application system. application_prefixes
    # are checked separately by normalize() against each actual application URL.


def collect(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    taxonomy = Taxonomy(args.keywords)
    config = load_yaml(args.companies)
    companies = config.get("companies")

    if not isinstance(companies, list):
        raise ValueError("companies.yaml must contain a top-level companies list.")

    jobs: list[dict[str, Any]] = []
    source_stats: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for company in companies:
        if not isinstance(company, dict):
            source_stats.append({"status": "skipped", "reason": "Invalid company entry."})
            continue
        if not company.get("enabled", False):
            continue

        name = str(company.get("name") or "<unnamed>")
        stats: dict[str, Any] = {
            "company": name,
            "adapter": company.get("adapter"),
            "status": "ok",
            "fetched": 0,
            "accepted": 0,
            "rejected_records": 0,
        }

        try:
            _validate_source_config(company)
            source = _build_source(company)
            raw_jobs = source.fetch_jobs()
            if not isinstance(raw_jobs, list):
                raise ValueError("Source adapter must return a list of postings.")
            stats["fetched"] = len(raw_jobs)

            for raw in raw_jobs:
                if not isinstance(raw, dict):
                    stats["rejected_records"] += 1
                    continue
                try:
                    job = normalize(company, raw, taxonomy)
                except (TypeError, ValueError, KeyError):
                    # A malformed posting should not make an otherwise working
                    # source disappear. The source itself is still considered valid.
                    stats["rejected_records"] += 1
                    continue

                if job["id"] in seen_ids:
                    continue
                seen_ids.add(job["id"])
                jobs.append(job)
                stats["accepted"] += 1

        except Exception as exc:  # source failure should be visible in output
            stats.update({
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            })

        source_stats.append(stats)

    return jobs, {
        "sources": source_stats,
        "collected_jobs": len(jobs),
    }


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: job[key] for key in PUBLIC_FIELDS if key in job}


def process(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    taxonomy: Taxonomy,
    settings: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validate_settings(settings)

    ranked: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    today = date.today()

    for job in jobs:
        screening = evaluate(
            job,
            taxonomy,
            allow_hybrid=settings.get("allow_hybrid", False),
            today=today,
        )
        if not screening["eligible"]:
            for reason in screening["reasons"]:
                rejected[reason] += 1
            continue

        ranked_job = rank_job(
            profile,
            job,
            taxonomy,
            settings,
            today=today,
        )
        ranked_job["tips"] = generate_tips(profile, ranked_job, taxonomy)
        ranked.append(ranked_job)

    ranked = sort_jobs(ranked)
    return ranked, {
        "eligible_jobs": len(ranked),
        "rejected_jobs": len(jobs) - len(ranked),
        "rejection_reasons": dict(rejected.most_common()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find, screen, rank and generate application tips for electronics jobs."
    )
    parser.add_argument(
        "--resume",
        required=True,
        help="Path to the candidate resume PDF.",
    )
    parser.add_argument(
        "--companies",
        default=str(ROOT / "config" / "companies.yaml"),
        help="Path to companies.yaml.",
    )
    parser.add_argument(
        "--keywords",
        default=str(ROOT / "config" / "keywords.yaml"),
        help="Path to keywords.yaml.",
    )
    parser.add_argument(
        "--scoring",
        default=str(ROOT / "config" / "scoring.yaml"),
        help="Path to scoring.yaml.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "outputs" / "jobs.json"),
        help="Output JSON path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        taxonomy = Taxonomy(args.keywords)
        scoring = load_yaml(args.scoring)
        validate_settings(scoring)

        profile = validate_profile(parse_pdf(args.resume, taxonomy))
        jobs, collection_stats = collect(args)
        ranked, processing_stats = process(jobs, profile, taxonomy, scoring)

        output = {
            "generated_at": timestamp(),
            "screening_date": date.today().isoformat(),
            # Never publish the candidate's local filesystem path.
            "resume": Path(args.resume).name,
            "collection": collection_stats,
            "processing": processing_stats,
            "jobs": [_public_job(job) for job in ranked],
        }
        save_json(args.output, output)

        print(f"Collected: {collection_stats['collected_jobs']}")
        print(f"Eligible:  {processing_stats['eligible_jobs']}")
        print(f"Rejected:  {processing_stats['rejected_jobs']}")
        print(f"Output:    {Path(args.output).resolve()}")
        return 0

    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
