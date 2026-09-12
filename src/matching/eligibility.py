import re
from datetime import date, datetime

from src.matching.skills import contains


def parse_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        ).date()
    except ValueError:
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None


def experience_evidence(job):
    """
    Conservative English-language screening.

    Returns eligible, minimum years found, and an explanation.
    This is not a guarantee of employer eligibility.
    """
    title = job.get("title") or ""
    description = job.get("description") or ""

    if re.search(
        r"\b(?:senior|sr\.?|principal|staff|lead|manager|director)\b",
        title,
        re.I,
    ):
        return False, None, "Senior or leadership title."

    minima = []

    pattern = re.compile(
        r"\b(\d+)"
        r"(?:\s*[-–]\s*(\d+))?"
        r"\s*\+?\s*years?"
        r"\s+(?:of\s+)?"
        r"(?:(?:relevant|professional|industry|industrial|work|"
        r"commercial|engineering|hands-on|related)\s+)*"
        r"experience\b",
        re.I,
    )

    for sentence in re.split(r"[.!?\n;]", description):
        preferred = re.search(
            r"\b(?:preferred|desirable|nice to have|bonus)\b",
            sentence,
            re.I,
        )
        required = re.search(
            r"\b(?:required|must|minimum|at least)\b",
            sentence,
            re.I,
        )

        if preferred and not required:
            continue

        for match in pattern.finditer(sentence):
            minima.append(int(match.group(1)))

        reverse = re.search(
            r"\bexperience\s*:\s*(\d+)"
            r"(?:\s*[-–]\s*\d+)?\s*\+?\s*years?\b",
            sentence,
            re.I,
        )
        if reverse:
            minima.append(int(reverse.group(1)))

    minimum = max(minima) if minima else None

    if minimum is not None and minimum > 1:
        return False, minimum, "Posting asks for more than one year."

    entry_title = re.search(
        r"\b(?:intern|internship|fresher|graduate|entry[- ]level)\b",
        title,
        re.I,
    )
    explicit_entry = re.search(
        r"\b(?:no (?:prior |previous )?experience required|"
        r"freshers? (?:can apply|welcome)|"
        r"new graduates? (?:can apply|welcome)|"
        r"entry[- ]level position)\b",
        description,
        re.I,
    )

    if entry_title or explicit_entry or minimum is not None:
        return True, minimum, "Entry-level evidence found."

    return False, None, "Entry-level eligibility is not explicit."


def evaluate(job, taxonomy, allow_hybrid=False, today=None):
    today = today or date.today()
    reasons = []

    if job.get("country") not in {"India", "Japan"}:
        reasons.append("Country is outside India/Japan or unknown.")

    accepted_modes = {"onsite"}
    if allow_hybrid:
        accepted_modes.add("hybrid")

    if job.get("work_mode") not in accepted_modes:
        reasons.append("Work arrangement is unsupported or unknown.")

    title = job.get("title") or ""
    description = job.get("description") or ""

    # Title evidence is stronger than incidental electronics words in a
    # company's general description.
    relevant = (
        any(contains(title, term) for term in taxonomy.role_terms)
        or bool(taxonomy.extract(title))
    )

    if not relevant:
        reasons.append("No configured electronics role evidence in title.")

    # A relevant title is still required for these exclusions.
    if re.search(
        r"\b(?:sales|recruiter|recruitment|marketing|accountant)\b",
        title,
        re.I,
    ):
        reasons.append("Non-engineering role.")

    entry, minimum, experience_reason = experience_evidence(job)
    if not entry:
        reasons.append(experience_reason)

    deadline = parse_date(job.get("deadline"))
    if deadline and deadline < today:
        reasons.append("Application deadline has passed.")

    return {
        "eligible": not reasons,
        "reasons": reasons,
        "minimum_experience_years": minimum,
        "experience_evidence": experience_reason,
        "notice": (
            "Automated screening only. Check degree, graduation intake, "
            "language, work authorization and all official requirements."
        ),
    }
