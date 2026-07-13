"""T016/T017 [US1] — work-mode classification and JSearch normalization.

Maps source-shaped raw postings onto the canonical Job dict
(contracts/source_mapping.md). Absent optional fields are always left `None`
— never fabricated (FR-010) — and a posting missing both identity fields
(title, company) is unnormalizable and skipped (FR-011).
"""

from __future__ import annotations

from jobhunter.discovery.dedup import compute_id

_REMOTE_KEYWORDS = ("remote", "work from home", "wfh", "fully remote")
_HYBRID_KEYWORDS = ("hybrid",)
_ONSITE_KEYWORDS = ("onsite", "on-site", "in office", "in-office")


def classify_work_mode(explicit_remote: bool | None, text: str) -> str:
    """Classify work mode: explicit flag first, else a keyword scan, else `"unknown"`.

    An explicit `True` remote flag always wins, even over conflicting text,
    since it reflects the source's own structured signal. Text is only
    consulted when that flag is absent or `False` — and even then, no
    keyword match means `"unknown"` rather than a guess.
    """
    if explicit_remote is True:
        return "remote"

    lowered = text.lower()
    if any(keyword in lowered for keyword in _REMOTE_KEYWORDS):
        return "remote"
    if any(keyword in lowered for keyword in _HYBRID_KEYWORDS):
        return "hybrid"
    if any(keyword in lowered for keyword in _ONSITE_KEYWORDS):
        return "onsite"
    return "unknown"


def normalize_jsearch(raw: dict) -> dict | None:
    """Map one raw JSearch posting to the canonical Job dict, or `None` if unusable.

    JSearch's own `job_id` is aggregate-derived across publishers, not a
    stable per-posting identity, so the idempotency key always uses the
    `compute_id` fallback composite rather than trusting `job_id` directly.
    """
    title = raw.get("job_title")
    company = raw.get("employer_name")
    city = raw.get("job_city")
    description = raw.get("job_description")

    job_id = compute_id(
        source="jsearch",
        source_id=raw.get("job_id"),
        id_is_stable=False,
        title=title,
        company=company,
        city=city,
    )
    if job_id is None:
        return None

    min_salary = raw.get("job_min_salary")
    max_salary = raw.get("job_max_salary")
    salary = None
    if min_salary is not None and max_salary is not None:
        period = raw.get("job_salary_period")
        salary = f"{int(min_salary)}-{int(max_salary)} {period}"

    text = f"{title or ''} {description or ''}"
    work_mode = classify_work_mode(explicit_remote=raw.get("job_is_remote"), text=text)

    return {
        "source": "jsearch",
        "title": title,
        "company": company,
        "location": raw.get("job_location"),
        "city": city,
        "country": raw.get("job_country"),
        "work_mode": work_mode,
        "description": description,
        "employment_type": raw.get("job_employment_type"),
        "salary": salary,
        "apply_url": raw.get("job_apply_link"),
        "id": job_id,
    }


def normalize_adzuna(raw: dict) -> dict | None:
    """Map one raw Adzuna posting to the canonical Job dict, or `None` if unusable.

    Adzuna's own `id` is reasonably stable per posting, so the idempotency key
    uses it directly (`"adzuna:<id>"`). The normalized `title|company|city`
    composite is additionally recorded as `dedup_key` — JSearch always
    resolves through that same composite, so it's the only way a JSearch and
    Adzuna copy of the same role can be recognized as a duplicate within a run
    (contracts/source_mapping.md "Cross-source dedup").
    """
    title = raw.get("title")
    company = (raw.get("company") or {}).get("display_name")
    if not title and not company:
        return None

    location = raw.get("location") or {}
    area = location.get("area") or []
    city = area[-1] if len(area) > 1 else ""
    country = area[0] if area else ""
    description = raw.get("description")

    job_id = compute_id(
        source="adzuna",
        source_id=raw.get("id"),
        id_is_stable=True,
        title=title,
        company=company,
        city=city,
    )
    if job_id is None:
        return None

    dedup_key = compute_id(
        source="adzuna",
        source_id=None,
        id_is_stable=False,
        title=title,
        company=company,
        city=city,
    )

    min_salary = raw.get("salary_min")
    max_salary = raw.get("salary_max")
    salary = None
    if min_salary is not None and max_salary is not None:
        salary = f"{int(min_salary)}-{int(max_salary)}"
        if raw.get("salary_is_predicted") == "1":
            salary += " (predicted)"

    text = f"{title or ''} {description or ''}"
    work_mode = classify_work_mode(explicit_remote=None, text=text)

    return {
        "source": "adzuna",
        "title": title,
        "company": company,
        "location": location.get("display_name"),
        "city": city,
        "country": country,
        "work_mode": work_mode,
        "description": description,
        "employment_type": raw.get("contract_time") or raw.get("contract_type"),
        "salary": salary,
        "apply_url": raw.get("redirect_url"),
        "id": job_id,
        "dedup_key": dedup_key,
    }
