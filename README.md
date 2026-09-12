# ECE Job Finder — Job Search Automation

A Python-based job-discovery and ranking pipeline for electronics and hardware roles in **India and Japan**.

The project is designed around a simple workflow:

**Resume PDF → candidate profile → official career sources → normalized jobs → eligibility screening → resume/job matching → ranking → application tips → `jobs.json` → browser dashboard**

The project does **not** automatically submit job applications. It sends the user to the employer's official application page.

## What it does

- Parses a text-based resume PDF with PyMuPDF.
- Extracts candidate degree, field, graduation year, experience level, skills and project-section text.
- Uses a configurable electronics/VLSI/communications skill taxonomy.
- Collects postings from explicitly configured official sources.
- Supports three source adapters:
  - **Greenhouse** public boards
  - **Lever** public postings
  - **HTML career pages** containing `JobPosting` JSON-LD
- Verifies HTTPS URLs and configured official application URL prefixes.
- Checks `robots.txt`, applies request pacing, follows only bounded HTTPS redirects, and limits response size.
- Screens jobs conservatively for:
  - India or Japan
  - on-site work by default
  - electronics/hardware relevance in the job title
  - entry-level suitability
  - experience requirements
  - expired deadlines
- Scores eligible jobs using configurable weights for skills, domain, education, experience, projects, location, on-site status and fresher fit.
- Generates rule-based resume and interview-preparation tips.
- Produces a JSON dataset for the included static web dashboard.

## Project structure

```text
job-search-automation/
├── config/
│   ├── companies.yaml       # enabled employers and source configuration
│   ├── keywords.yaml        # skills, categories and title-role terms
│   └── scoring.yaml         # scoring weights and priority rules
├── src/
│   ├── main.py              # command-line pipeline entry point
│   ├── resume/
│   │   └── parser.py        # PDF → candidate profile
│   ├── collectors/
│   │   ├── company_sources.py # shared HTTP, URL validation, normalization
│   │   ├── greenhouse.py       # Greenhouse adapter
│   │   ├── lever.py            # Lever adapter
│   │   └── html_scraper.py     # JobPosting JSON-LD adapter
│   ├── matching/
│   │   ├── skills.py         # taxonomy and skill comparison
│   │   ├── eligibility.py    # conservative eligibility screening
│   │   └── ranking.py        # weighted ranking and priority scoring
│   └── tips/
│       └── generator.py      # rule-based application/interview tips
├── tests/
│   └── test_core.py          # core tests when present in the checkout
├── web/
│   ├── index.html            # dashboard UI
│   ├── style.css             # dashboard styling
│   └── app.js                # dataset loading, filtering and rendering
├── requirements.txt
└── README.md
