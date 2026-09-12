TOPICS = {
    "UVM": "Review UVM components, sequences and scoreboards.",
    "CDC": "Review synchronizers, metastability and asynchronous FIFOs.",
    "Verilog": "Review sequential logic, combinational logic and synthesis.",
    "SystemVerilog": "Review SystemVerilog types, interfaces and assertions.",
    "RTL": "Review reset design, pipelining and synthesizable RTL.",
    "FPGA": "Review FPGA implementation, timing constraints and resource use.",
    "AXI": "Review AXI channels, handshakes, bursts and backpressure.",
    "STA": "Review setup/hold analysis and timing constraints.",
    "C++": "Review pointers, object lifetimes and standard containers.",
    "DSP": "Review sampling, filtering and fixed-point arithmetic.",
    "OFDM": "Review FFT processing, cyclic prefixes and synchronization.",
    "RF": "Review impedance matching, noise figure and RF measurements.",
}


def generate_tips(profile, ranked_job, taxonomy):
    matches = ranked_job["matches"]
    strong = matches["strong"]
    partial = matches["partial"]
    missing = matches["missing"]

    resume_changes = []
    if strong:
        resume_changes.append(
            "Make demonstrated experience with "
            + ", ".join(strong[:5])
            + " easy to find on your resume."
        )

    project_skills = set()
    for project in profile.get("projects") or []:
        project_skills.update(taxonomy.extract(project))

    relevant = sorted(project_skills & set(ranked_job.get("skills") or []))
    if relevant:
        # Avoid publishing private project titles or resume text.
        resume_changes.append(
            "Highlight an existing project demonstrating "
            + ", ".join(relevant[:4])
            + "; explain your contribution and measurable results."
        )

    if partial:
        resume_changes.append(
            "Related-domain knowledge is not proof of proficiency in "
            + ", ".join(partial[:5])
            + ". Describe your actual experience accurately."
        )

    interview_topics = []
    for skill in dict.fromkeys(missing + partial + strong):
        topic = TOPICS.get(skill)
        if topic and topic not in interview_topics:
            interview_topics.append(topic)

    if not resume_changes:
        resume_changes.append(
            "Compare the official requirements with your actual coursework "
            "and projects before deciding whether to apply."
        )

    checks = [
        "Verify degree level, graduation intake and experience requirements.",
        "Confirm the job remains open on the official application page.",
        "Do not add unearned skills or qualifications to your resume.",
    ]

    if ranked_job.get("country") == "Japan":
        checks.append(
            "Check the posting for language, international-applicant and "
            "visa requirements; unknown does not mean unrestricted."
        )

    return {
        "resume_changes": resume_changes,
        "interview_topics": interview_topics[:5],
        "checks": checks,
        "recommendation": {
            "HIGH": "REVIEW AND APPLY",
            "MEDIUM": "CONSIDER APPLYING",
            "LOW": "LOW PRIORITY",
        }[ranked_job["application_priority"]],
    }
