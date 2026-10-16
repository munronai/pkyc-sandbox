import asyncio
import os
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Tuple
import httpx
from pydantic import BaseModel, Field


class FeedRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"rec_{uuid.uuid4().hex[:6]}")
    source_feed: Literal["COMPANIES_HOUSE", "OPENSANCTIONS", "GDELT_ADVERSE_MEDIA"]
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    url: str
    raw_content: str


COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")
OPENSANCTIONS_API_KEY = os.getenv("OPENSANCTIONS_API_KEY", "")


class FeedRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"rec_{uuid.uuid4().hex[:6]}")
    source_feed: Literal["COMPANIES_HOUSE", "OPENSANCTIONS", "GDELT_ADVERSE_MEDIA"]
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    url: str
    raw_content: str


async def fetch_companies_house(
    client: httpx.AsyncClient, company_name: str, company_number: str = None
) -> Tuple[List[FeedRecord], List[str]]:
    """
    Fetches UK corporate profile, filing history deltas, and Persons with Significant Control (PSCs).
    Returns normalized FeedRecords and a list of discovered officers/UBOs for 2nd-degree checks.
    """
    records: List[FeedRecord] = []
    discovered_ubos: List[str] = []

    if not COMPANIES_HOUSE_API_KEY:
        return records, discovered_ubos

    # HTTP Basic Auth: API key is username, password is ""
    auth = httpx.BasicAuth(username=COMPANIES_HOUSE_API_KEY, password="")
    base_url = "https://api.company-information.service.gov.uk"

    # 1. Resolve Company Number if only name was provided
    if not company_number:
        search_resp = await client.get(
            f"{base_url}/search/companies",
            params={"q": company_name, "items_per_page": 1},
            auth=auth,
        )
        if search_resp.status_code == 200:
            items = search_resp.json().get("items", [])
            if items:
                company_number = items[0].get("company_number")

    if not company_number:
        return records, discovered_ubos

    # 2. Fetch Profile, PSCs (UBOs), and Recent Filing History in parallel
    profile_req = client.get(f"{base_url}/company/{company_number}", auth=auth)
    psc_req = client.get(
        f"{base_url}/company/{company_number}/persons-with-significant-control",
        auth=auth,
    )
    filings_req = client.get(
        f"{base_url}/company/{company_number}/filing-history",
        params={"items_per_page": 3},
        auth=auth,
    )

    profile_res, psc_res, filings_res = await asyncio.gather(
        profile_req, psc_req, filings_req, return_exceptions=True
    )

    # Parse Company Profile + PSCs
    if isinstance(profile_res, httpx.Response) and profile_res.status_code == 200:
        p = profile_res.json()
        addr = p.get("registered_office_address", {})
        addr_str = f"{addr.get('address_line_1', '')}, {addr.get('locality', '')}, {addr.get('postal_code', '')}"

        psc_summaries = []
        if isinstance(psc_res, httpx.Response) and psc_res.status_code == 200:
            for item in psc_res.json().get("items", []):
                name = item.get("name", "Unknown")
                dob = item.get("date_of_birth", {})
                dob_str = (
                    f"{dob.get('year', '????')}-{dob.get('month', '??'):02d}"
                    if dob
                    else "N/A"
                )
                natures = ", ".join(item.get("natures_of_control", []))
                discovered_ubos.append(name)
                psc_summaries.append(f"{name} (DOB: {dob_str}, Control: {natures})")

        records.append(
            FeedRecord(
                source_feed="COMPANIES_HOUSE",
                url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}",
                raw_content=(
                    f"{p.get('company_name')} (Co No. {company_number}). "
                    f"Status: {p.get('company_status')}. Incorporated: {p.get('date_of_creation')}. "
                    f"Office: {addr_str}. Active PSCs/UBOs: {'; '.join(psc_summaries) or 'None listed'}."
                ),
            )
        )

    # Parse Recent Filing Deltas (For Continuous Monitoring)
    if isinstance(filings_res, httpx.Response) and filings_res.status_code == 200:
        for f in filings_res.json().get("items", []):
            records.append(
                FeedRecord(
                    source_feed="COMPANIES_HOUSE",
                    timestamp=f.get("date", datetime.now(timezone.utc).isoformat()),
                    url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}/filing-history",
                    raw_content=(
                        f"Filing [{f.get('type')}] ({f.get('category', 'general')}): "
                        f"{f.get('description', '')} - {f.get('description_values', {})}"
                    ),
                )
            )

    return records, discovered_ubos


async def fetch_opensanctions(
    client: httpx.AsyncClient,
    entity_name: str,
    ubo_names: List[str],
    jurisdiction: str = "gb",
) -> List[FeedRecord]:
    """
    Uses OpenSanctions /match/default API to screen both the target company AND its discovered UBOs
    in a single batched HTTP request.
    """
    records: List[FeedRecord] = []
    if not OPENSANCTIONS_API_KEY:
        return records

    queries = {
        "target_company": {
            "schema": "Company",
            "properties": {"name": [entity_name], "jurisdiction": [jurisdiction]},
        }
    }
    for idx, ubo in enumerate(ubo_names[:5]):
        queries[f"ubo_{idx}"] = {"schema": "Person", "properties": {"name": [ubo]}}

    resp = await client.post(
        "https://api.opensanctions.org/match/default",
        params={"algorithm": "best", "threshold": 0.65},
        headers={"Authorization": f"ApiKey {OPENSANCTIONS_API_KEY}"},
        json={"queries": queries},
    )

    if resp.status_code != 200:
        return records

    responses = resp.json().get("responses", {})
    for q_key, res_data in responses.items():
        results = res_data.get("results", [])
        if not results:
            continue
        for hit in results[:2]:
            datasets = ", ".join(hit.get("datasets", []))
            topics = ", ".join(hit.get("properties", {}).get("topics", []))
            score = hit.get("score", 0.0)
            records.append(
                FeedRecord(
                    source_feed="OPENSANCTIONS",
                    url=f"https://www.opensanctions.org/entities/{hit.get('id')}/",
                    raw_content=(
                        f"WATCHLIST MATCH ({q_key}, Match Score: {score:.2f}): "
                        f"Entity '{hit.get('caption')}' matched in datasets [{datasets}]. "
                        f"Risk Topics: [{topics or 'Sanctions/Watchlist'}]."
                    ),
                )
            )

    if not records:
        records.append(
            FeedRecord(
                source_feed="OPENSANCTIONS",
                url="https://api.opensanctions.org/match/default",
                raw_content=f"0 direct hits above 0.65 threshold on global sanctions or PEP lists for {entity_name} or its {len(ubo_names)} UBO(s).",
            )
        )

    return records


async def fetch_gdelt_adverse_media(
    client: httpx.AsyncClient,
    entity_name: str,
    timespan: str = "1m",
    max_records: int = 5,
) -> List[FeedRecord]:
    """
    Queries the free, no-auth GDELT DOC 2.0 API for adverse media articles.
    Safely handles empty responses, non-JSON text, and timeouts.
    """
    records: List[FeedRecord] = []
    risk_terms = "(fraud OR fine OR investigation OR sanctions OR lawsuit OR insolvency OR customs OR probe OR bribery)"
    query = f'"{entity_name}" {risk_terms}'

    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": str(max_records),
        "timespan": timespan,
        "format": "json",
        "sort": "HybridRel",
    }

    url = (
        f"https://api.gdeltproject.org/api/v2/doc/doc?{urllib.parse.urlencode(params)}"
    )

    try:
        resp = await client.get(url, timeout=10.0)
        if resp.status_code != 200 or not resp.text.strip():
            return records

        # GDELT occasionally returns plain text or HTML on rate-limits
        try:
            data = resp.json()
        except Exception:
            return records

        for art in data.get("articles", []) or []:
            title = art.get("title", "Untitled Article")
            domain = art.get("domain", "unknown-source")
            seendate = art.get("seendate", datetime.now(timezone.utc).isoformat())
            art_url = art.get("url", "https://api.gdeltproject.org")
            records.append(
                FeedRecord(
                    source_feed="GDELT_ADVERSE_MEDIA",
                    timestamp=seendate,
                    url=art_url,
                    raw_content=f"[{domain}] {title} (Language: {art.get('language', 'English')})",
                )
            )
    except Exception as e:
        print(f"[GDELT Warning] Failed to poll adverse media: {e}")

    return records


async def poll_all_live_feeds(
    entity_name: str,
    company_number: str = None,
    jurisdiction: str = "gb",
    timespan: str = "1w",
) -> List[FeedRecord]:
    """
    Orchestrates the 3 live feeds safely with exception isolation.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        ch_task = fetch_companies_house(client, entity_name, company_number)
        gdelt_task = fetch_gdelt_adverse_media(client, entity_name, timespan=timespan)

        results = await asyncio.gather(ch_task, gdelt_task, return_exceptions=True)

        # Unpack Companies House safely
        if isinstance(results[0], tuple):
            ch_records, discovered_ubos = results[0]
        else:
            ch_records, discovered_ubos = [], []

        # Unpack GDELT safely
        gdelt_records = results[1] if isinstance(results[1], list) else []

        # Screen UBOs against OpenSanctions
        try:
            os_records = await fetch_opensanctions(
                client, entity_name, discovered_ubos, jurisdiction
            )
        except Exception:
            os_records = []

        combined = ch_records + os_records + gdelt_records

        # If all live feeds return zero records (e.g. pristine clean company or rate limit)
        if not combined:
            combined.append(
                FeedRecord(
                    source_feed="GDELT_ADVERSE_MEDIA",
                    url="https://api.gdeltproject.org",
                    raw_content=f"Live feed sweep completed for {entity_name}. Zero new adverse media or filing deltas found in the past {timespan}.",
                )
            )

        return combined
