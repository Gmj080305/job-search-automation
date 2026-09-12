"use strict";

const $ = (id) => document.getElementById(id);
const state = { jobs: [], loading: false };

const filterFields = [
  ["country", "country", "All countries"],
  ["city", "city", "All cities"],
  ["company", "company", "All companies"],
  ["work-mode", "work_mode", "All work modes"],
  ["employment", "employment", "All types"],
];

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}

function stringList(value) {
  if (typeof value === "string") {
    return value.trim() ? [value.trim()] : [];
  }

  if (!Array.isArray(value)) return [];

  return [...new Set(value.filter(
    (item) => typeof item === "string" && item.trim()
  ).map((item) => item.trim()))];
}

function element(tag, className = "", content = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== "") node.textContent = content;
  return node;
}

function normalizeScore(value) {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    typeof value === "boolean"
  ) return null;

  if (typeof value !== "number" && typeof value !== "string") return null;

  const number = Number(value);
  if (!Number.isFinite(number) || number < 0 || number > 100) return null;
  return number;
}

function timestamp(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  const result = Date.parse(value);
  return Number.isFinite(result) ? result : null;
}

function formatDate(value) {
  const time = timestamp(value);
  if (time === null) return "Not stated";

  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(time));
}

function deadlineTimestamp(value) {
  const raw = text(value);
  // A date-only deadline remains open through that UTC calendar day.
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    return timestamp(`${raw}T23:59:59.999Z`);
  }
  return timestamp(raw);
}

function httpsUrl(value) {
  try {
    const url = new URL(text(value));
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password
    ) return null;

    return url.href;
  } catch {
    return null;
  }
}

function normalizePriority(value) {
  const raw = typeof value === "object" && value !== null
    ? text(value.label || value.level)
    : text(value);

  const key = raw.toLowerCase().replace(/[_-]+/g, " ").trim();

  if (["high", "apply now", "high priority"].includes(key)) return "high";
  if (["medium", "apply", "medium priority"].includes(key)) return "medium";
  if (["low", "low priority"].includes(key)) return "low";
  return "unknown";
}

function normalizeTips(value) {
  if (typeof value === "string" || Array.isArray(value)) {
    return stringList(value);
  }

  if (!value || typeof value !== "object") return [];

  // Support structured rule-based tip output as well as string arrays.
  const labels = {
    resume_changes: "Resume",
    resume_improvements: "Resume",
    relevant_projects: "Relevant project",
    interview_topics: "Prepare",
    likely_interview_topics: "Prepare",
    interview_questions: "Practice question",
    recommendations: "Recommendation",
    tips: "",
  };

  return [...new Set(Object.entries(labels).flatMap(([key, label]) =>
    stringList(value[key]).map((item) => label ? `${label}: ${item}` : item)
  ))];
}

function normalizeJob(raw) {
  const explanations =
    raw.explanation && typeof raw.explanation === "object"
      ? raw.explanation
      : {};

  const job = {
    company: text(raw.company) || "Company not stated",
    title: text(raw.title) || "Untitled role",
    country: text(raw.country),
    city: text(raw.city),
    work_mode: text(raw.work_mode),
    employment: text(raw.employment),
    experience: text(raw.experience),
    description: text(raw.description),
    posted_date: text(raw.posted_date),
    deadline: text(raw.deadline),
    score: normalizeScore(raw.match_score ?? raw.score),
    priority: normalizePriority(raw.application_priority ?? raw.priority),
    matched: stringList(
      raw.matched_skills ?? raw.strong_matches ??
      explanations.matched_skills ?? explanations.strong_matches
    ),
    partial: stringList(
      raw.partial_matches ?? raw.partial_skills ??
      explanations.partial_matches
    ),
    missing: stringList(
      raw.missing_skills ?? explanations.missing_skills
    ),
    skills: stringList(raw.skills),
    tips: normalizeTips(raw.application_tips ?? raw.tips),
    application_url: httpsUrl(raw.application_url),
    source_url: httpsUrl(raw.source_url),
    status: text(raw.status).toLowerCase(),
    available: raw.available,
    is_new: raw.is_new === true,
    japan: {},
  };

  // Keep unknown Japan requirements unknown: never coerce strings or null.
  for (const key of [
    "japanese_required",
    "english_required",
    "international_applicant",
    "visa_support",
  ]) {
    if (typeof raw[key] === "boolean") job.japan[key] = raw[key];
  }

  job.searchText = [
    job.company, job.title, job.country, job.city, job.description,
    job.experience, ...job.skills, ...job.matched,
    ...job.partial, ...job.missing,
  ].join(" ").toLowerCase();

  return job;
}

function unavailable(job) {
  const closed = [
    "expired", "closed", "unavailable", "no longer available",
    "no_longer_available",
  ].includes(job.status);

  const deadline = deadlineTimestamp(job.deadline);
  return closed || job.available === false ||
    (deadline !== null && deadline < Date.now());
}

function populateFilters() {
  for (const [id, field, label] of filterFields) {
    const select = $(id);
    const previous = select.value;

    select.replaceChildren(new Option(label, ""));

    const values = [...new Set(
      state.jobs.map((job) => job[field]).filter(Boolean)
    )].sort((a, b) => a.localeCompare(b));

    for (const value of values) select.add(new Option(value, value));
    if (values.includes(previous)) select.value = previous;
  }
}

function selectedJobs() {
  const query = $("search").value.trim().toLowerCase();
  const words = query.split(/\s+/).filter(Boolean);
  const minimum = Number($("minimum").value);
  const cutoff = deadlineTimestamp($("deadline").value);

  const jobs = state.jobs.filter((job) => {
    if (!words.every((word) => job.searchText.includes(word))) return false;

    for (const [id, field] of filterFields) {
      if ($(id).value && $(id).value !== job[field]) return false;
    }

    if (minimum > 0 && (job.score === null || job.score < minimum)) return false;
    if ($("hide-expired").checked && unavailable(job)) return false;

    if (cutoff !== null) {
      const deadline = deadlineTimestamp(job.deadline);
      if (deadline === null || deadline > cutoff) return false;
    }

    return true;
  });

  const priorityOrder = { high: 3, medium: 2, low: 1, unknown: 0 };
  const byMatch = (a, b) => (b.score ?? -1) - (a.score ?? -1);

  jobs.sort((a, b) => {
    let difference = 0;

    switch ($("sort").value) {
      case "priority":
        difference = priorityOrder[b.priority] - priorityOrder[a.priority];
        break;

      case "newest":
        difference =
          (timestamp(b.posted_date) ?? 0) - (timestamp(a.posted_date) ?? 0);
        break;

      case "deadline": {
        const first = deadlineTimestamp(a.deadline);
        const second = deadlineTimestamp(b.deadline);
        difference = first === second ? 0 :
          first === null ? 1 :
          second === null ? -1 :
          first - second;
        break;
      }

      case "company":
        difference = a.company.localeCompare(b.company);
        break;

      default:
        difference = byMatch(a, b);
    }

    return difference || byMatch(a, b) || a.title.localeCompare(b.title);
  });

  return jobs;
}

function appendSkills(card, title, skills, type) {
  if (!skills.length) return;

  card.append(element("p", "skill-heading", title));
  const list = element("ul", "skill-list");

  for (const skill of skills) {
    list.append(element("li", `skill ${type}`, skill));
  }

  card.append(list);
}

function externalLink(label, url, secondary = false) {
  const link = element(
    "a",
    `button${secondary ? " secondary" : ""}`,
    label
  );

  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.setAttribute("aria-label", `${label} (opens in a new tab)`);
  return link;
}

function jobCard(job, index) {
  const card = element("article", "job-card");
  const headingId = `job-title-${index}`;
  card.setAttribute("aria-labelledby", headingId);

  const top = element("div", "job-topline");
  top.append(element("p", "company-name", job.company));

  const priorityLabel = job.priority === "unknown"
    ? "Priority not provided"
    : `${job.priority.toUpperCase()} priority`;

  top.append(element("span", `badge ${job.priority}`, priorityLabel));
  card.append(top);

  const title = element("h3", "job-title", job.title);
  title.id = headingId;
  card.append(title);

  const location = [job.city, job.country].filter(Boolean).join(", ");
  card.append(element(
    "p",
    "job-meta",
    location || "Location not stated"
  ));

  const badges = element("div", "badges");
  for (const label of [job.work_mode, job.employment, job.experience]) {
    if (label) badges.append(element("span", "badge", label));
  }

  if (job.is_new) badges.append(element("span", "badge high", "New"));
  if (unavailable(job)) {
    badges.append(element("span", "badge low", "Expired / unavailable"));
  }

  card.append(badges);

  const scoreBlock = element("div", "score-block");
  const scoreLabel = element("div", "score-label");
  scoreLabel.append(
    element("span", "", "Resume match"),
    element(
      "strong",
      "",
      job.score === null ? "Not scored" : `${Math.round(job.score)}%`
    )
  );
  scoreBlock.append(scoreLabel);

  if (job.score !== null) {
    const progress = element("progress");
    progress.max = 100;
    progress.value = job.score;
    progress.setAttribute("aria-label", `Resume match for ${job.title}`);
    scoreBlock.append(progress);
  }

  card.append(scoreBlock);

  appendSkills(card, "Strong matches", job.matched, "strong");
  appendSkills(card, "Partial matches", job.partial, "partial");
  appendSkills(card, "Missing skills", job.missing, "missing");

  if (!job.matched.length && !job.partial.length && !job.missing.length) {
    card.append(element(
      "p",
      "muted",
      "A skill-level explanation was not provided."
    ));
  }

  const dates = [
    `Posted: ${formatDate(job.posted_date)}`,
    `Deadline: ${formatDate(job.deadline)}`,
  ];
  const dateParagraph = element("p", "job-meta", dates.join(" · "));
  dateParagraph.style.marginTop = "18px";
  card.append(dateParagraph);

  if (job.country.toLowerCase() === "japan") {
    const labels = {
      japanese_required: "Japanese required",
      english_required: "English required",
      international_applicant: "International applicants accepted",
      visa_support: "Visa support",
    };

    for (const [key, label] of Object.entries(labels)) {
      if (Object.hasOwn(job.japan, key)) {
        card.append(element(
          "p",
          "job-meta",
          `${label}: ${job.japan[key] ? "Yes" : "No"}`
        ));
      }
    }

    if (!Object.keys(job.japan).length) {
      card.append(element(
        "p",
        "job-meta",
        "Language, international eligibility, and visa support: not stated."
      ));
    }
  }

  if (job.tips.length) {
    const details = element("details");
    details.append(element("summary", "", "Application tips"));

    const list = element("ul", "tips-list");
    for (const tip of job.tips) list.append(element("li", "", tip));

    details.append(list);
    card.append(details);
  }

  if (job.description) {
    const details = element("details");
    details.append(
      element("summary", "", "Job description"),
      element("p", "job-description", job.description)
    );
    card.append(details);
  }

  const actions = element("div", "job-actions");

  if (job.source_url) {
    actions.append(externalLink("View job", job.source_url, true));
  }

  if (job.application_url && !unavailable(job)) {
    actions.append(externalLink("Apply", job.application_url));
  } else {
    const button = element(
      "button",
      "button",
      unavailable(job) ? "Application closed" : "Application link unavailable"
    );
    button.type = "button";
    button.disabled = true;
    actions.append(button);
  }

  card.append(actions);
  return card;
}

function render() {
  const jobs = selectedJobs();
  const fragment = document.createDocumentFragment();

  jobs.forEach((job, index) => fragment.append(jobCard(job, index)));
  $("jobs").replaceChildren(fragment);

  $("total-count").textContent = String(state.jobs.length);
  $("visible-count").textContent = String(jobs.length);
  $("high-count").textContent = String(
    jobs.filter((job) => job.priority === "high" && !unavailable(job)).length
  );
  $("minimum-output").textContent = `${$("minimum").value}%`;

  $("empty-state").hidden = jobs.length > 0;
  $("empty-message").textContent = state.jobs.length
    ? "Try reducing the minimum match or clearing some filters."
    : "The dataset contains no jobs. Check the collection pipeline and enabled sources.";

  $("status").textContent =
    `Showing ${jobs.length} of ${state.jobs.length} jobs.`;
}

async function loadJobs() {
  if (state.loading) return;

  state.loading = true;
  $("reload").disabled = true;
  $("jobs").setAttribute("aria-busy", "true");
  $("status").textContent = "Loading jobs…";
  $("source-warning").hidden = true;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);

  try {
    const response = await fetch("./jobs.json", {
      cache: "no-store",
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    const rows = Array.isArray(payload) ? payload : payload?.jobs;

    if (!Array.isArray(rows)) {
      throw new Error('Expected a job array or an object containing "jobs".');
    }

    if (rows.some(
      (row) => !row || typeof row !== "object" || Array.isArray(row)
    )) {
      throw new Error("Each job must be a JSON object.");
    }

    const normalized = rows.map(normalizeJob);
    state.jobs = normalized;
    populateFilters();

    const generated = !Array.isArray(payload)
      ? payload.generated_at ?? payload.updated_at
      : null;

    $("updated-at").textContent = timestamp(generated) === null
      ? "Dataset update time not provided."
      : `Dataset updated: ${new Date(generated).toLocaleString()}`;

    const errors = !Array.isArray(payload)
      ? payload.source_errors ?? payload.errors
      : null;

    const hasErrors = Array.isArray(errors)
      ? errors.length > 0
      : errors && typeof errors === "object"
        ? Object.keys(errors).length > 0
        : Boolean(errors);

    if (hasErrors) {
      $("source-warning").textContent =
        "Some career sources reported errors. Results may be incomplete; check the pipeline logs.";
      $("source-warning").hidden = false;
    }

    render();
  } catch (error) {
    const reason = error.name === "AbortError"
      ? "The request timed out."
      : error.message;

    $("status").textContent =
      `Unable to load jobs.json. ${reason} ` +
      (state.jobs.length
        ? "Previously loaded results remain visible."
        : "Ensure the pipeline publishes jobs.json beside index.html.");

    if (!state.jobs.length) {
      $("empty-state").hidden = false;
      $("empty-message").textContent =
        "No dataset is loaded. Use an HTTP server for local preview, then select Refresh data.";
    }
  } finally {
    clearTimeout(timeout);
    state.loading = false;
    $("reload").disabled = false;
    $("jobs").setAttribute("aria-busy", "false");
  }
}

$("filters-form").addEventListener("submit", (event) => {
  event.preventDefault();
});

$("filters-form").addEventListener("input", render);
$("filters-form").addEventListener("change", render);

$("reset-filters").addEventListener("click", () => {
  $("filters-form").reset();
  render();
});

$("reload").addEventListener("click", loadJobs);

loadJobs();
