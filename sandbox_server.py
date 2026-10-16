import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from mcp.server.mcpserver import MCPServer
from fastapi.middleware.cors import CORSMiddleware
from live_feeds import (
    FeedRecord,
    poll_all_live_feeds,
    fetch_companies_house,
    fetch_gdelt_adverse_media,
    fetch_opensanctions,
)

app = FastAPI(title="munron pKYC Simulation Sandbox", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional Modal Dict Persistence (falls back to in-memory locally)
try:
    import modal

    MODAL_STATE = modal.Dict.from_name("xapien-sandbox-store", create_if_missing=True)
except Exception:
    MODAL_STATE = None

# =====================================================================
# 1. DATA MODELS & SCHEMAS
# =====================================================================


class PolicyThresholds(BaseModel):
    jev_mode: Literal["simulated", "live"] = Field(
        "simulated",
        description="Toggle between offline calibrated simulation and live TypeSafe AI Jev API",
    )
    sector: str = "Fintech / Banking"
    risk_appetite: Literal["Conservative", "Balanced", "Aggressive"] = "Conservative"
    disambiguation_cutoff: float = Field(
        0.65, description="Minimum Jev Noul probability to match identity"
    )
    novelty_cutoff: float = Field(
        0.50, description="Minimum Jev Noul probability that event is net-new"
    )
    notify_threshold: float = Field(
        0.65, description="Jev Score threshold to recommend report refresh"
    )
    auto_regen_threshold: float = Field(
        0.88, description="Jev Score threshold to auto-trigger System 2 LLM"
    )


class JevEvaluation(BaseModel):
    engine_used: Literal["JEV_SIMULATED", "JEV_LIVE_API"] = "JEV_SIMULATED"
    is_same_entity_prob: float
    is_net_new_event_prob: float
    risk_category: str
    regeneration_urgency_level: str
    worth_a_report_score: float
    action_taken: Literal[
        "DISCARDED_FALSE_POSITIVE",
        "DISCARDED_DUPLICATE_ECHO",
        "LOGGED_SILENT_ADMIN_DELTA",
        "QUEUED_FOR_USER_APPROVAL",
        "AUTO_TRIGGERED_REPORT_REFRESH",
    ]
    reasoning_note: str
    estimated_cost_usd: float = 0.0004  # System 1 inference cost


class MonitoringEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:6]}")
    entity_id: str
    scenario_name: Optional[str] = None
    record: FeedRecord
    jev_evaluation: JevEvaluation
    processed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class DueDiligenceReport(BaseModel):
    report_id: str = Field(default_factory=lambda: f"rep_{uuid.uuid4().hex[:6]}")
    version: int
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    overall_risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    jev_calibrated_risk_score: float
    executive_summary: str
    corporate_structure_findings: List[str]
    sanctions_and_peps_findings: List[str]
    adverse_media_findings: List[str]
    audit_citations: List[FeedRecord]
    llm_synthesis_cost_usd: float = 0.42  # System 2 full synthesis cost


class MonitoredEntity(BaseModel):
    entity_id: str
    name: str
    company_number: str
    jurisdiction: str
    known_officers: List[str]
    monitoring_active: bool = True
    reports: List[DueDiligenceReport] = []
    event_stream: List[MonitoringEvent] = []
    pending_refresh_events: List[MonitoringEvent] = []


class InjectDeltaRequest(BaseModel):
    entity_id: str = "ent_apex_01"
    scenario_preset: Optional[
        Literal[
            "1_namesake_noise",
            "2_routine_admin",
            "3_syndicated_echo",
            "4_ambiguous_media",
            "5_silent_ubo_sanctions",
        ]
    ] = "4_ambiguous_media"
    custom_record: Optional[FeedRecord] = None


class OnboardLiveRequest(BaseModel):
    company_name: str
    company_number: Optional[str] = None
    jurisdiction: str = "GB"


# =====================================================================
# 2. IN-MEMORY SANDBOX STATE & GOLDEN PERSONA SEED
# =====================================================================


class SandboxStore:
    def __init__(self):
        self.policy = PolicyThresholds()
        self.entities: Dict[str, MonitoredEntity] = {}
        # Synchronous seed for initial boot
        self._build_golden_persona()

    def _build_golden_persona(self):
        baseline_records = [
            FeedRecord(
                id="rec_base1",
                source_feed="COMPANIES_HOUSE",
                url="https://find-and-update.company-information.service.gov.uk/company/10928374",
                raw_content="Apex Global Logistics Ltd (Co No. 10928374). Status: Active. Incorporated: 2017. Registered Office: 10 Bishopsgate, London. Active Director & PSC: Sterling Vance (DOB: 1978-04, Nationality: British).",
            ),
            FeedRecord(
                id="rec_base2",
                source_feed="OPENSANCTIONS",
                url="https://api.opensanctions.org/entities/search?q=Apex+Global+Logistics",
                raw_content="0 direct hits on OFAC, UK HMT, or EU Consolidated Sanctions lists for Apex Global Logistics Ltd or Sterling Vance (DOB 1978-04).",
            ),
            FeedRecord(
                id="rec_base3",
                source_feed="GDELT_ADVERSE_MEDIA",
                url="https://uk-maritime-press.example.com/2024/apex-late-filing-resolved",
                raw_content="In 2024, Apex Global Logistics Ltd paid a minor £1,500 administrative penalty to HMRC regarding a delayed customs declaration form, which was fully resolved without further investigation.",
            ),
        ]

        baseline_report = DueDiligenceReport(
            report_id="rep_baseline_v1",
            version=1,
            overall_risk_level="LOW",
            jev_calibrated_risk_score=0.18,
            executive_summary=(
                "Apex Global Logistics Ltd (10928374) is an active UK freight forwarder controlled by director "
                "Sterling Vance (born April 1978) [rec_base1]. Screening against global watchlists returned zero "
                "matches [rec_base2]. Historical adverse media is limited to a minor, resolved £1,500 HMRC administrative "
                "customs filing penalty in 2024 [rec_base3]."
            ),
            corporate_structure_findings=[
                "Incorporated in England & Wales (10928374) at 10 Bishopsgate, London [rec_base1].",
                "Sole Person with Significant Control (PSC): Sterling Vance (DOB: 1978-04) [rec_base1].",
            ],
            sanctions_and_peps_findings=[
                "No Sanctions or PEP matches identified [rec_base2]."
            ],
            adverse_media_findings=[
                "Resolved 2024 minor £1,500 HMRC administrative customs filing penalty [rec_base3]."
            ],
            audit_citations=baseline_records,
        )

        self.entities = {
            "ent_apex_01": MonitoredEntity(
                entity_id="ent_apex_01",
                name="Apex Global Logistics Ltd",
                company_number="10928374",
                jurisdiction="GB",
                known_officers=["Sterling Vance (DOB: 1978-04)"],
                reports=[baseline_report],
            )
        }

    async def load_or_seed(self):
        """Asynchronous state loader using Modal's .aio interface."""
        if MODAL_STATE is not None:
            try:
                has_entities = await MODAL_STATE.contains.aio("entities")
                has_policy = await MODAL_STATE.contains.aio("policy")
                if has_entities and has_policy:
                    policy_data = await MODAL_STATE.get.aio("policy")
                    entities_data = await MODAL_STATE.get.aio("entities")
                    self.policy = PolicyThresholds(**policy_data)
                    self.entities = {
                        k: MonitoredEntity(**v) for k, v in entities_data.items()
                    }
                    return
            except Exception:
                pass
        await self.seed_golden_persona(persist=True)

    async def clear_and_seed(self):
        """Forces an absolute wipe of remote state and reseeds baseline."""
        self.policy = PolicyThresholds()
        self._build_golden_persona()
        if MODAL_STATE is not None:
            try:
                # Clear all entries from the persistent modal.Dict
                await MODAL_STATE.clear.aio()
                # Re-populate clean baseline
                await MODAL_STATE.put.aio("policy", self.policy.model_dump())
                await MODAL_STATE.put.aio(
                    "entities", {k: v.model_dump() for k, v in self.entities.items()}
                )
            except Exception as e:
                print(f"[Clear & Seed Error]: {e}")

    async def save(self):
        """Asynchronous state saver using Modal's .aio interface."""
        if MODAL_STATE is not None:
            try:
                await MODAL_STATE.put.aio("policy", self.policy.model_dump())
                await MODAL_STATE.put.aio(
                    "entities", {k: v.model_dump() for k, v in self.entities.items()}
                )
            except Exception:
                pass

    async def seed_golden_persona(self, persist: bool = False):
        self._build_golden_persona()
        if persist:
            await self.save()


STORE = SandboxStore()

# =====================================================================
# 3. FIVE PRE-BUILT SANDBOX SCENARIOS
# =====================================================================

SANDBOX_SCENARIOS: Dict[str, FeedRecord] = {
    "1_namesake_noise": FeedRecord(
        source_feed="GDELT_ADVERSE_MEDIA",
        url="https://miami-herald-crime.example.com/2026/sterling-vance-tax-fraud",
        raw_content="Florida luxury realtor Sterling Vance (age 35, born 1991) was indicted today in Miami federal court on $4.2M wire and tax fraud charges.",
    ),
    "2_routine_admin": FeedRecord(
        source_feed="COMPANIES_HOUSE",
        url="https://find-and-update.company-information.service.gov.uk/company/10928374/filing-history/adm02",
        raw_content="Form AD01 filed for Apex Global Logistics Ltd (10928374): Registered office address changed from 10 Bishopsgate, London to 14 Bishopsgate, Suite 4B, London.",
    ),
    "3_syndicated_echo": FeedRecord(
        source_feed="GDELT_ADVERSE_MEDIA",
        url="https://freight-blog-digest.example.com/2026/retrospective-2024-hmrc-fines",
        raw_content="Industry Recap: Looking back at 2024 compliance stats, UK firm Apex Global Logistics Ltd was among companies paying a £1,500 administrative penalty to HMRC for a late customs form.",
    ),
    "4_ambiguous_media": FeedRecord(
        source_feed="GDELT_ADVERSE_MEDIA",
        url="https://east-anglia-shipping-news.example.com/2026/felixstowe-customs-probe",
        raw_content="Regional trade sources allege UK freight firm Apex Global Logistics Ltd is facing an unconfirmed inquiry by Port of Felixstowe authorities regarding misdeclared chemical warehouse manifests.",
    ),
    "5_silent_ubo_sanctions": FeedRecord(
        source_feed="OPENSANCTIONS",
        url="https://api.opensanctions.org/entities/ofac-99281-dmitri-kovalev",
        raw_content="ALERT: Companies House PSC01 filing adds Dmitri Kovalev (DOB: 1969-11) as 50% beneficial owner of Apex Global Logistics Ltd. Child OpenSanctions check matched Dmitri Kovalev (DOB: 1969-11) to OFAC SDN & UK Sanctions List (Maritime sanctions evasion network).",
    ),
}

# =====================================================================
# 4. SYSTEM 1 ENGINE: TYPESAFE AI'S JEV MATERIALITY GATEKEEPER
# =====================================================================

URGENCY_LEVELS = [
    "0_Ignore_False_Positive_Or_Duplicate",
    "1_Log_Silently_In_Audit_Trail",
    "2_Include_In_Weekly_Digest_No_Report",
    "3_Notify_Customer_Recommend_Report_Refresh",
    "4_Critical_Auto_Trigger_Full_Report",
]


async def evaluate_delta_with_jev(
    entity: MonitoredEntity,
    record: FeedRecord,
    policy: PolicyThresholds,
    scenario_hint: Optional[str] = None,
) -> JevEvaluation:
    """
    Constructs the exact TypeSafe AI Jev payload (`noul`, `choice`, `score`).
    Routes to live TypeSafe AI Jev API when policy.jev_mode == "live"; otherwise runs deterministic calibrated simulation.
    """
    latest_report = entity.reports[-1]
    jev_payload = {
        "model": "jev-latest",
        "state": {
            "monitored_entity": {
                "name": entity.name,
                "company_number": entity.company_number,
                "jurisdiction": entity.jurisdiction,
                "known_officers": entity.known_officers,
                "baseline_risk_summary": latest_report.executive_summary,
            },
            "client_policy": policy.model_dump(),
            "incoming_delta": record.model_dump(),
        },
        "questions": {
            "is_same_entity": {
                "type": "noul",
                "question": "Does incoming_delta refer to the exact monitored_entity or its known_officers?",
            },
            "is_net_new_event": {
                "type": "noul",
                "question": "Does incoming_delta describe a new event NOT already covered in baseline_risk_summary?",
            },
            "risk_category": {
                "type": "choice",
                "question": "Which primary risk category describes incoming_delta?",
                "choices": [
                    "Sanctions_PEP",
                    "Financial_Crime",
                    "Corporate_UBO_Change",
                    "Insolvency",
                    "ESG_Reputational",
                    "Routine_Admin",
                    "Benign_Unrelated",
                ],
            },
            "regeneration_urgency": {
                "type": "score",
                "question": "Given client_policy, how urgently does this update warrant paying for a full due diligence report regeneration?",
                "levels": URGENCY_LEVELS,
            },
        },
    }

    api_key = os.getenv("TYPESAFE_API_KEY")
    engine_used: Literal["JEV_SIMULATED", "JEV_LIVE_API"] = "JEV_SIMULATED"

    # Route to Live TypeSafe AI Jev API when policy.jev_mode == "live"
    if policy.jev_mode == "live":
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="Jev Mode is set to 'live', but TYPESAFE_API_KEY environment variable is not set.",
            )
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                os.getenv("TYPESAFE_API_URL", "https://api.typesafe.ai/v1/evaluate"),
                headers={"Authorization": f"Bearer {api_key}"},
                json=jev_payload,
            )
            resp.raise_for_status()
            data = resp.json()

            # Support both direct question keys and nested 'answers'/'results' objects
            answers = data.get("answers", data.get("results", data))
            same_prob = float(
                answers["is_same_entity"].get(
                    "probability", answers["is_same_entity"].get("true_prob", 0.5)
                )
            )
            new_prob = float(
                answers["is_net_new_event"].get(
                    "probability", answers["is_net_new_event"].get("true_prob", 0.5)
                )
            )
            category = answers["risk_category"].get(
                "top_choice",
                answers["risk_category"].get("choice", "ESG_Reputational"),
            )
            urgency_level = answers["regeneration_urgency"].get(
                "top_level", URGENCY_LEVELS[2]
            )
            worth_score = float(
                answers["regeneration_urgency"].get(
                    "calibrated_score",
                    answers["regeneration_urgency"].get("expected_score", 0.5),
                )
            )
            engine_used = "JEV_LIVE_API"
    else:
        # Calibrated System 1 Simulation for Offline Demo
        same_prob, new_prob, category, urgency_level, worth_score = (
            _simulate_jev_distributions(record, scenario_hint)
        )

    # Apply Policy Threshold Gatekeeping
    if same_prob < policy.disambiguation_cutoff:
        action = "DISCARDED_FALSE_POSITIVE"
        note = f"[{engine_used}] Filtered by Jev Noul disambiguation ({same_prob:.2f} < {policy.disambiguation_cutoff} cutoff)."
    elif new_prob < policy.novelty_cutoff:
        action = "DISCARDED_DUPLICATE_ECHO"
        note = f"[{engine_used}] Filtered by Jev Noul novelty check ({new_prob:.2f} < {policy.novelty_cutoff} cutoff). Event already in baseline."
    elif worth_score >= policy.auto_regen_threshold:
        action = "AUTO_TRIGGERED_REPORT_REFRESH"
        note = f"[{engine_used}] Critical materiality ({worth_score:.2f} >= {policy.auto_regen_threshold}). Auto-triggering System 2 LLM synthesis."
    elif worth_score >= policy.notify_threshold:
        action = "QUEUED_FOR_USER_APPROVAL"
        note = f"[{engine_used}] Material update detected ({worth_score:.2f} >= {policy.notify_threshold}). Queued for customer approval."
    else:
        action = "LOGGED_SILENT_ADMIN_DELTA"
        note = f"[{engine_used}] Low materiality score ({worth_score:.2f}). Appended to audit log without LLM cost."

    return JevEvaluation(
        engine_used=engine_used,
        is_same_entity_prob=same_prob,
        is_net_new_event_prob=new_prob,
        risk_category=category,
        regeneration_urgency_level=urgency_level,
        worth_a_report_score=worth_score,
        action_taken=action,
        reasoning_note=note,
    )


def _simulate_jev_distributions(record: FeedRecord, scenario_hint: Optional[str]):
    text = record.raw_content.lower()
    if (
        scenario_hint == "1_namesake_noise"
        or "born 1991" in text
        or "delaware" in text
        or "nevada" in text
    ):
        return 0.08, 0.99, "Benign_Unrelated", URGENCY_LEVELS[0], 0.04
    if scenario_hint == "2_routine_admin" or "form ad01" in text or "filing [" in text:
        return 0.99, 0.95, "Routine_Admin", URGENCY_LEVELS[1], 0.28
    if (
        scenario_hint == "3_syndicated_echo"
        or "looking back at 2024" in text
        or "looking back at how" in text
        or "0 direct hits" in text
    ):
        return 0.98, 0.06, "Routine_Admin", URGENCY_LEVELS[0], 0.11
    if (
        scenario_hint == "5_silent_ubo_sanctions"
        or "ofac" in text
        or "watchlist match" in text
    ):
        return 0.97, 0.99, "Sanctions_PEP", URGENCY_LEVELS[4], 0.97
    # Default / 4_ambiguous_media
    return 0.87, 0.94, "ESG_Reputational", URGENCY_LEVELS[3], 0.76


# =====================================================================
# 5. SYSTEM 2 ENGINE: CITED REPORT SYNTHESIS LOOP
# =====================================================================


async def synthesize_updated_report(
    entity: MonitoredEntity, new_events: List[MonitoringEvent]
) -> DueDiligenceReport:
    """
    Takes the prior baseline report + newly approved Jev-verified deltas and synthesizes
    a newly versioned, inline-cited due diligence report.
    """
    prev_report = entity.reports[-1]
    new_version = prev_report.version + 1
    all_citations = prev_report.audit_citations + [e.record for e in new_events]

    highest_jev = max(
        [e.jev_evaluation.worth_a_report_score for e in new_events]
        + [prev_report.jev_calibrated_risk_score]
    )
    if highest_jev >= 0.88:
        risk_level = "CRITICAL"
    elif highest_jev >= 0.65:
        risk_level = "HIGH"
    elif highest_jev >= 0.35:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    corp_findings = list(prev_report.corporate_structure_findings)
    sanctions_findings = list(prev_report.sanctions_and_peps_findings)
    media_findings = list(prev_report.adverse_media_findings)
    summary_additions = []

    for evt in new_events:
        rec = evt.record
        cat = evt.jev_evaluation.risk_category
        citation_tag = f"[{rec.id}]"
        if cat == "Sanctions_PEP" or rec.source_feed == "OPENSANCTIONS":
            sanctions_findings = [f"CRITICAL ALERT: {rec.raw_content} {citation_tag}"]
            corp_findings.append(
                f"Beneficial Ownership / Watchlist Alert {citation_tag}."
            )
            summary_additions.append(
                f"CRITICAL UPDATE (v{new_version}): Watchlist / Sanctions hit detected {citation_tag}."
            )
        elif rec.source_feed == "COMPANIES_HOUSE":
            corp_findings.append(f"Registry Update: {rec.raw_content} {citation_tag}")
            summary_additions.append(f"Corporate filing update logged {citation_tag}.")
        else:
            media_findings.append(
                f"Adverse Media (Jev Confidence {evt.jev_evaluation.worth_a_report_score:.0%}): {rec.raw_content} {citation_tag}"
            )
            summary_additions.append(
                f"MATERIAL UPDATE (v{new_version}): Adverse media surfaced ({rec.raw_content[:90]}...) {citation_tag}."
            )

    new_summary = prev_report.executive_summary + " " + " ".join(summary_additions)

    new_report = DueDiligenceReport(
        version=new_version,
        overall_risk_level=risk_level,
        jev_calibrated_risk_score=round(highest_jev, 2),
        executive_summary=new_summary,
        corporate_structure_findings=corp_findings,
        sanctions_and_peps_findings=sanctions_findings,
        adverse_media_findings=media_findings,
        audit_citations=all_citations,
    )
    entity.reports.append(new_report)
    await STORE.save()
    return new_report


# =====================================================================
# 6. CORE ORCHESTRATION WORKFLOW
# =====================================================================


async def process_incoming_delta(req: InjectDeltaRequest) -> dict:
    await STORE.load_or_seed()
    entity = STORE.entities.get(req.entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity {req.entity_id} not found")

    if req.custom_record:
        record = req.custom_record
        scenario_label = "live_or_custom_delta"
    elif req.scenario_preset and req.scenario_preset in SANDBOX_SCENARIOS:
        template = SANDBOX_SCENARIOS[req.scenario_preset]
        record = FeedRecord(
            source_feed=template.source_feed,
            url=template.url,
            raw_content=template.raw_content,
        )
        scenario_label = req.scenario_preset
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either a valid scenario_preset or custom_record",
        )

    jev_eval = await evaluate_delta_with_jev(
        entity, record, STORE.policy, scenario_label
    )
    event = MonitoringEvent(
        entity_id=entity.entity_id,
        scenario_name=scenario_label,
        record=record,
        jev_evaluation=jev_eval,
    )
    entity.event_stream.append(event)

    auto_generated_report = None
    if jev_eval.action_taken == "QUEUED_FOR_USER_APPROVAL":
        entity.pending_refresh_events.append(event)
    elif jev_eval.action_taken == "AUTO_TRIGGERED_REPORT_REFRESH":
        auto_generated_report = await synthesize_updated_report(entity, [event])

    await STORE.save()
    return {
        "event": event,
        "auto_generated_report": auto_generated_report,
        "telemetry": get_telemetry_summary(entity),
    }


def get_telemetry_summary(entity: MonitoredEntity) -> dict:
    total_events = len(entity.event_stream)
    llm_runs_triggered = len(entity.reports) - 1  # Exclude v1 baseline
    events_filtered_by_jev = total_events - llm_runs_triggered
    jev_spend = round(total_events * 0.0004, 4)
    llm_spend = round(llm_runs_triggered * 0.42, 2)
    naive_llm_spend = round(total_events * 0.42, 2)
    return {
        "total_deltas_evaluated": total_events,
        "filtered_by_jev_system1": events_filtered_by_jev,
        "system2_llm_regenerations": llm_runs_triggered,
        "pending_user_approval": len(entity.pending_refresh_events),
        "actual_compute_spend_usd": round(jev_spend + llm_spend, 4),
        "naive_always_llm_spend_usd": naive_llm_spend,
        "estimated_cost_savings_usd": round(
            max(0.0, naive_llm_spend - (jev_spend + llm_spend)), 4
        ),
    }


# =====================================================================
# 7. FASTMCP SERVER SURFACE (RESOURCES & TOOLS FOR LLMs)
# =====================================================================

mcp = MCPServer("Xapien-pKYC-Sandbox")


@mcp.resource("dd://entities/{entity_id}/latest-report")
async def mcp_get_latest_report(entity_id: str) -> str:
    """Returns the latest structured Due Diligence report and citation trail for an entity."""
    await STORE.load_or_seed()
    entity = STORE.entities.get(entity_id)
    if not entity:
        return f"Error: Entity {entity_id} not found."
    return entity.reports[-1].model_dump_json(indent=2)


@mcp.resource("dd://monitoring/triage-queue")
async def mcp_get_triage_queue() -> str:
    """Returns all monitored entities that have pending material updates awaiting report refresh approval."""
    await STORE.load_or_seed()
    queue = {}
    for eid, ent in STORE.entities.items():
        if ent.pending_refresh_events:
            queue[eid] = {
                "entity_name": ent.name,
                "pending_events": [e.model_dump() for e in ent.pending_refresh_events],
            }
    return str(queue)


@mcp.tool()
async def simulate_monitoring_event(
    scenario_preset: Literal[
        "1_namesake_noise",
        "2_routine_admin",
        "3_syndicated_echo",
        "4_ambiguous_media",
        "5_silent_ubo_sanctions",
    ],
    entity_id: str = "ent_apex_01",
) -> dict:
    """
    Injects one of the 5 synthetic continuous monitoring scenarios into the Sandbox
    and returns Jev's System 1 materiality evaluation and cost-saving telemetry.
    """
    req = InjectDeltaRequest(entity_id=entity_id, scenario_preset=scenario_preset)
    return await process_incoming_delta(req)


@mcp.tool()
async def poll_live_open_data(
    entity_id: str = "ent_apex_01", timespan: str = "1w"
) -> dict:
    """Polls live UK Companies House, OpenSanctions, and GDELT DOC 2.0 feeds for an entity."""
    return await poll_live_entity_feeds(entity_id=entity_id, timespan=timespan)


@mcp.tool()
async def approve_report_refresh(entity_id: str = "ent_apex_01") -> dict:
    """
    Triggers the System 2 LLM to synthesize a new report version incorporating all pending
    material events in the entity's triage queue.
    """
    await STORE.load_or_seed()
    entity = STORE.entities.get(entity_id)
    if not entity or not entity.pending_refresh_events:
        return {"status": "No pending events require report synthesis."}
    events_to_fold = list(entity.pending_refresh_events)
    entity.pending_refresh_events.clear()
    new_report = await synthesize_updated_report(entity, events_to_fold)
    return {
        "status": f"Report upgraded to v{new_report.version}",
        "new_report": new_report.model_dump(),
    }


# =====================================================================
# 8. FASTAPI REST ENDPOINTS
# =====================================================================


@app.get("/api/v1/entities")
async def list_entities():
    await STORE.load_or_seed()
    return {
        eid: {
            "name": e.name,
            "company_number": e.company_number,
            "jurisdiction": e.jurisdiction,
        }
        for eid, e in STORE.entities.items()
    }


@app.get("/api/v1/entities/{entity_id}/report", response_model=DueDiligenceReport)
async def get_latest_report(entity_id: str = "ent_apex_01"):
    """Fetch the latest synthesized Due Diligence report for an entity."""
    await STORE.load_or_seed()
    entity = STORE.entities.get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity.reports[-1]


@app.get("/api/v1/entities/{entity_id}/events")
async def get_monitoring_stream(entity_id: str = "ent_apex_01"):
    """Returns every weekly delta evaluated by Jev (including discarded false positives) + cost telemetry."""
    await STORE.load_or_seed()
    entity = STORE.entities.get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "company_number": entity.company_number,
        "jurisdiction": entity.jurisdiction,
        "active_policy": STORE.policy,
        "telemetry": get_telemetry_summary(entity),
        "pending_approval_queue": entity.pending_refresh_events,
        "audit_event_stream": entity.event_stream,
    }


@app.post("/api/v1/sandbox/inject-delta")
async def inject_sandbox_delta(req: InjectDeltaRequest):
    """Injects a preset scenario or custom feed delta and runs the Jev Materiality Gatekeeper."""
    return await process_incoming_delta(req)


@app.post(
    "/api/v1/entities/{entity_id}/approve-refresh", response_model=DueDiligenceReport
)
async def approve_pending_refresh(entity_id: str = "ent_apex_01"):
    """Approves pending Tier-2 alerts and runs the System 2 LLM to produce a new report version."""
    await STORE.load_or_seed()
    entity = STORE.entities.get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    if not entity.pending_refresh_events:
        raise HTTPException(
            status_code=400, detail="No pending material events in queue to refresh."
        )
    events_to_fold = list(entity.pending_refresh_events)
    entity.pending_refresh_events.clear()
    return await synthesize_updated_report(entity, events_to_fold)


@app.put("/api/v1/sandbox/policy-thresholds", response_model=PolicyThresholds)
async def update_policy_thresholds(new_policy: PolicyThresholds):
    """Tune Jev Engine Mode, Noul disambiguation, and Score materiality thresholds on the fly."""
    await STORE.load_or_seed()
    STORE.policy = new_policy
    await STORE.save()
    return STORE.policy


@app.post("/api/v1/sandbox/reset")
async def reset_sandbox():
    """Resets the sandbox back to the clean v1 baseline report and clears Modal Dict state."""
    await STORE.clear_and_seed()
    return {"status": "Sandbox reset to v1 baseline."}


@app.post("/api/v1/entities/{entity_id}/poll-live-feeds")
async def poll_live_entity_feeds(entity_id: str = "ent_apex_01", timespan: str = "1w"):
    """Polls live UK Companies House, OpenSanctions, and GDELT feeds and filters through Jev."""
    await STORE.load_or_seed()
    entity = STORE.entities.get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    live_records = await poll_all_live_feeds(
        entity_name=entity.name,
        company_number=(
            entity.company_number if entity.company_number != "N/A" else None
        ),
        jurisdiction=entity.jurisdiction.lower(),
        timespan=timespan,
    )
    results = []
    for rec in live_records:
        res = await process_incoming_delta(
            InjectDeltaRequest(
                entity_id=entity_id, scenario_preset=None, custom_record=rec
            )
        )
        results.append(res["event"])
    return {"polled_records_count": len(results), "evaluated_events": results}


@app.post("/api/v1/entities/onboard-live")
async def onboard_live_entity(req: OnboardLiveRequest):
    """Onboards a real-world company using live feeds and extracts real PSCs/UBOs for Jev disambiguation."""
    await STORE.load_or_seed()
    new_id = f"ent_{uuid.uuid4().hex[:6]}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        (ch_records, discovered_ubos), gdelt_records = await asyncio.gather(
            fetch_companies_house(client, req.company_name, req.company_number),
            fetch_gdelt_adverse_media(client, req.company_name, timespan="3m"),
        )
        os_records = await fetch_opensanctions(
            client, req.company_name, discovered_ubos, req.jurisdiction.lower()
        )
        live_records = ch_records + os_records + gdelt_records

    if not live_records:
        live_records = [
            FeedRecord(
                source_feed="GDELT_ADVERSE_MEDIA",
                url="https://api.gdeltproject.org",
                raw_content=f"Initial live open-source sweep completed for {req.company_name}. No critical adverse media in past 90 days.",
            )
        ]

    corp = [
        r.raw_content for r in live_records if r.source_feed == "COMPANIES_HOUSE"
    ] or [f"Entity: {req.company_name} ({req.jurisdiction})"]
    sanc = [
        r.raw_content for r in live_records if r.source_feed == "OPENSANCTIONS"
    ] or ["No live watchlist matches returned."]
    media = [
        r.raw_content for r in live_records if r.source_feed == "GDELT_ADVERSE_MEDIA"
    ] or ["No recent adverse media articles returned."]

    base_rep = DueDiligenceReport(
        version=1,
        overall_risk_level="LOW",
        jev_calibrated_risk_score=0.22,
        executive_summary=(
            f"Live baseline due diligence report generated for {req.company_name} ({req.company_number or 'UK'}) "
            f"across {len(live_records)} open-source records. Active PSCs/Officers: {', '.join(discovered_ubos) or 'None listed in PSC feed'}."
        ),
        corporate_structure_findings=corp,
        sanctions_and_peps_findings=sanc,
        adverse_media_findings=media,
        audit_citations=live_records,
    )

    entity = MonitoredEntity(
        entity_id=new_id,
        name=req.company_name,
        company_number=req.company_number or "N/A",
        jurisdiction=req.jurisdiction,
        known_officers=discovered_ubos,
        reports=[base_rep],
    )
    STORE.entities[new_id] = entity
    await STORE.save()
    return {"entity_id": new_id, "entity": entity}


# Mount the FastMCP SSE app at /mcp so MCP clients can connect over HTTP alongside REST
app.mount("/mcp", mcp.sse_app())

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
