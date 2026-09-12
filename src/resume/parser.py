import re

import pymupdf

from src.matching.skills import Taxonomy, contains


def profile_from_text(text, taxonomy=None):
    taxonomy = taxonomy or Taxonomy()
    normalized = re.sub(r"[ \t]+", " ", text)

    degree = None
    for name, pattern in [
        ("M.Tech", r"\bm\.?\s*tech\b"),
        ("B.Tech", r"\bb\.?\s*tech\b"),
        ("M.E.", r"\bm\.?\s*e\.?(?=\s|$)"),
        ("B.E.", r"\bb\.?\s*e\.?(?=\s|$)"),
    ]:
        if re.search(pattern, normalized, re.I):
            degree = name
            break

    field = None
    if any(contains(normalized, term) for term in [
        "electronics and communication",
        "electronics & communication",
        "ECE",
    ]):
        field = "Electronics and Communication Engineering"
    elif contains(normalized, "electrical engineering"):
        field = "Electrical Engineering"
    elif contains(normalized, "electronics engineering"):
        field = "Electronics Engineering"

    graduation = re.search(
        r"(?:expected\s+)?graduation(?:\s+year)?"
        r"\s*[:\-]?\s*(20\d{2})",
        normalized,
        re.I,
    )

    # Preserve project-section lines without inventing project titles.
    projects = []
    in_projects = False
    stop_headings = {
        "education", "experience", "work experience", "skills",
        "technical skills", "certifications", "achievements",
        "publications", "interests",
    }

    for line in text.splitlines():
        line = line.strip()
        heading = line.rstrip(":").casefold()

        if heading in {"projects", "academic projects", "personal projects"}:
            in_projects = True
            continue
        if in_projects and heading in stop_headings:
            break
        if in_projects and line:
            projects.append(line)

    level = "unknown"
    if re.search(r"\b(?:currently pursuing|undergraduate student|student)\b",
                 normalized, re.I):
        level = "student"
    elif re.search(r"\b(?:fresher|recent graduate|new graduate)\b",
                   normalized, re.I):
        level = "fresher"

    return {
        "degree": degree,
        "field": field,
        "graduation_year": (
            int(graduation.group(1)) if graduation else None
        ),
        "experience_level": level,
        "skills": sorted(taxonomy.extract(normalized)),
        "projects": projects,
        "preferred_countries": ["India", "Japan"],
    }


def parse_pdf(path, taxonomy=None):
    with pymupdf.open(path) as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")
        text = "\n".join(page.get_text() for page in document)

    if len(text.strip()) < 30:
        raise ValueError(
            "No usable text found. Supply a text-based PDF; OCR is not included."
        )

    return profile_from_text(text, taxonomy)
