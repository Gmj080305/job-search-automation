import math
from datetime import date

from src.matching.eligibility import (
    evaluate,
    experience_evidence,
    parse_date,
)


FACTORS = {
    "skills", "domain", "education", "experience",
    "projects", "location", "onsite", "fresher",
}


def validate_settings(settings):
    weights = settings.get("weights", {})
    if set(weights) != FACTORS:
        raise ValueError("Scoring weights must define all eight factors.")

    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
        for value in weights.values()
    ):
        raise ValueError("Weights must be finite non-negative numbers.")

    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-8):
        raise ValueError("Scoring weights must add up to 1.")

    credit = settings.get("partial_skill_credit", 0.4)
    if not isinstance(credit, (int, float)) or not 0 <= credit <= 1:
        raise ValueError("partial_skill_credit must be between 0 and 1.")


def education_score(profile, job):
    if not profile.get("degree"):
        return 0.0

    field = str(profile.get("field") or "").casefold()
    candidate_fields = set()

    if "electronics and communication" in field or field == "ece":
        candidate_fields.add("ECE")
    if "electrical engineering" in field or field == "ee":
        candidate_fields.add("EE")
    if "electronics engineering" in field:
        candidate_fields.add("Electronics")

    required = set(job.get("degree") or [])
    if not required:
        return 0.0

    return 1.0 if candidate_fields & required else 0.0


def rank_job(profile, job, taxonomy, settings, today=None):
    validate_settings(settings)
    today = today or date.today()

    screening = evaluate(
        job,
        taxonomy,
        allow_hybrid=settings.get("allow_hybrid", False),
        today=today,
    )

    if not screening["eligible"]:
        raise ValueError("Only screened jobs can be ranked.")

    candidate = set(profile.get("skills") or [])
    required = set(job.get("skills") or [])
    comparison = taxonomy.compare(candidate, required)

    partial_credit = settings.get("partial_skill_credit", 0.4)

    skill_score = (
        (
            len(comparison["strong"])
            + partial_credit * len(comparison["partial"])
        ) / len(required)
        if required else 0.0
    )

    required_groups = taxonomy.groups(required)
    candidate_groups = taxonomy.groups(candidate)
    domain_score = (
        len(required_groups & candidate_groups) / len(required_groups)
        if required_groups else 0.0
    )

    project_skills = set()
    for project in profile.get("projects") or []:
        project_skills.update(taxonomy.extract(project))

    project_comparison = taxonomy.compare(project_skills, required)
    project_score = (
        (
            len(project_comparison["strong"])
            + partial_credit * len(project_comparison["partial"])
        ) / len(required)
        if required else 0.0
    )

    entry, minimum, _ = experience_evidence(job)
    level = str(profile.get("experience_level") or "").casefold()
    early_career = level in {"student", "fresher", "new_graduate"}

    years = profile.get("experience_years")
    if (
        isinstance(years, (int, float))
        and not isinstance(years, bool)
        and math.isfinite(years)
        and minimum is not None
    ):
        experience_score = float(years >= minimum)
    elif minimum == 0:
        experience_score = float(early_career)
    elif minimum is None and entry:
        experience_score = float(early_career)
    else:
        # Do not assume a student has one year of work experience.
        experience_score = 0.0

    preferred = profile.get("preferred_countries", ["India", "Japan"])

    factors = {
        "skills": skill_score,
        "domain": domain_score,
        "education": education_score(profile, job),
        "experience": experience_score,
        "projects": project_score,
        "location": float(job.get("country") in preferred),
        "onsite": float(job.get("work_mode") == "onsite"),
        "fresher": float(entry and early_career),
    }

    weights = settings["weights"]
    total = sum(weights[name] * factors[name] for name in FACTORS)
    match_score = round(100 * total, 1)

    priority_config = settings.get("priority", {})
    bonus = 0
    priority_reasons = []

    posted = parse_date(job.get("posted_date"))
    deadline = parse_date(job.get("deadline"))

    if posted:
        age = (today - posted).days
        if 0 <= age <= priority_config.get("recent_days", 7):
            bonus += priority_config.get("freshness_bonus", 5)
            priority_reasons.append("Recently posted.")

    if deadline:
        remaining = (deadline - today).days
        if 0 <= remaining <= priority_config.get("closing_days", 7):
            bonus += priority_config.get("deadline_bonus", 5)
            priority_reasons.append("Deadline is approaching.")

    priority_score = round(min(100, match_score + bonus), 1)

    if priority_score >= priority_config.get("high_minimum", 80):
        priority = "HIGH"
    elif priority_score >= priority_config.get("medium_minimum", 55):
        priority = "MEDIUM"
    else:
        priority = "LOW"

    result = dict(job)
    result.update({
        "match_score": match_score,
        "application_priority": priority,
        "priority_score": priority_score,
        "priority_reasons": priority_reasons,
        "matches": comparison,
        "project_matches": project_comparison["strong"],
        "score_breakdown": {
            name: {
                "factor_score": round(factors[name] * 100, 1),
                "weight": weights[name],
                "points": round(factors[name] * weights[name] * 100, 2),
            }
            for name in sorted(FACTORS)
        },
        "screening": screening,
    })
    return result


def sort_jobs(jobs):
    return sorted(
        jobs,
        key=lambda job: (
            -job["priority_score"],
            -job["match_score"],
            job["company"].casefold(),
            job["title"].casefold(),
            job["id"],
        ),
    )
