import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path

import yaml

from src.collectors.company_sources import normalize, official_url
from src.matching.eligibility import evaluate
from src.matching.ranking import rank_job, sort_jobs, validate_settings
from src.matching.skills import Taxonomy
from src.resume.parser import parse_pdf
from src.tips.generator import generate_tips


ADAPTERS = {
    "greenhouse": ("src.collectors.greenhouse", "GreenhouseSource"),
    "lever": ("src.collectors.lever", "LeverSource"),
    "html": ("src.collectors.html_scraper", "HTMLCareerSource"),
}

PUBLIC_FIELDS = {
    "id", "company", "title", "country", "city", "location",
    "work_mode", "employment", "degree", "skills",
    "application_url", "source_url", "posted_date", "deadline",
    "japanese_required", "english_required",
    "international_applicant", "visa_support",
    "match_score", "application_priority", "priority_score",
    "priority_reasons", "matches", "score_breakdown", "screening", "tips",
}


def load_yaml(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, value):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(destination)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def validate_profile(profile):
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

    return profile


def collect(args):
    taxonomy = Taxonomy(args.keywords)
    config = load_yaml(args.companies)
    companies = config.get("companies") if isinstance(config, dict) else None

    if not isinstance(companies, list):
       
