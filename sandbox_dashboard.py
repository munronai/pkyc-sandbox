import os
import streamlit as st
import httpx
import pandas as pd
import streamlit.components.v1 as components

# Automatically uses Modal's live HTTPS domain when deployed, or 127.0.0.1:8000 when running locally
API_BASE = os.getenv("SANDBOX_API_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
API_ROOT = API_BASE.replace("/api/v1", "")
MCP_URL = os.getenv("SANDBOX_MCP_URL", f"{API_ROOT}/mcp/sse")
DOCS_URL = os.getenv("SANDBOX_DOCS_URL", f"{API_ROOT}/docs")
ENTITY_ID = "ent_apex_01"

st.set_page_config(
    page_title="Xapien + Jev pKYC Sandbox",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def st_mermaid(mermaid_code: str, height: int = 620):
    html = f"""
    <div class="mermaid" style="display: flex; justify-content: center; background: #0e1117; padding: 16px; border-radius: 8px;">
        {mermaid_code}
    </div>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ startOnLoad: true, theme: 'dark' }});
    </script>
    """
    components.html(html, height=height, scrolling=True)


if "active_entity_id" not in st.session_state:
    st.session_state["active_entity_id"] = "ent_apex_01"

# =====================================================================
# API CLIENT HELPERS
# =====================================================================


def api_get_entities():
    try:
        with httpx.Client(timeout=10.0) as client:
            return client.get(f"{API_BASE}/entities").json()
    except Exception as e:
        st.error(f"Waiting for Sandbox API at {API_BASE}... ({e})")
        st.stop()


def api_get_state(entity_id: str):
    with httpx.Client(timeout=10.0) as client:
        rep = client.get(f"{API_BASE}/entities/{entity_id}/report").json()
        evts = client.get(f"{API_BASE}/entities/{entity_id}/events").json()
        return rep, evts


def api_inject_scenario(entity_id: str, preset: str = None, custom_record: dict = None):
    payload = {
        "entity_id": entity_id,
        "scenario_preset": preset,
        "custom_record": custom_record,
    }
    with httpx.Client(timeout=15.0) as client:
        return client.post(f"{API_BASE}/sandbox/inject-delta", json=payload).json()


def api_poll_live_feeds(entity_id: str, timespan: str = "1w"):
    with httpx.Client(timeout=25.0) as client:
        return client.post(
            f"{API_BASE}/entities/{entity_id}/poll-live-feeds",
            params={"timespan": timespan},
        ).json()


def api_onboard_live(company_name: str, company_number: str = None):
    with httpx.Client(timeout=30.0) as client:
        return client.post(
            f"{API_BASE}/entities/onboard-live",
            json={
                "company_name": company_name,
                "company_number": company_number or None,
                "jurisdiction": "GB",
            },
        ).json()


def api_approve_refresh(entity_id: str):
    with httpx.Client(timeout=20.0) as client:
        return client.post(f"{API_BASE}/entities/{entity_id}/approve-refresh").json()


def api_update_policy(policy_dict: dict):
    with httpx.Client(timeout=10.0) as client:
        return client.put(
            f"{API_BASE}/sandbox/policy-thresholds", json=policy_dict
        ).json()


def api_reset_sandbox():
    with httpx.Client(timeout=10.0) as client:
        client.post(f"{API_BASE}/sandbox/reset")
    st.session_state["active_entity_id"] = "ent_apex_01"
    # Clear any Streamlit memo/session caches if present
    for key in list(st.session_state.keys()):
        if key != "active_entity_id":
            del st.session_state[key]


# =====================================================================
# PAGE 1: HOMEPAGE (OVERVIEW & HOW TO USE)
# =====================================================================


def render_home_page():
    st.title("🛡️ Dynamic Due Diligence & pKYC Simulation Sandbox")
    st.subheader(
        "Solving Continuous Monitoring Unit Economics & Alert Fatigue with System 1 (Jev) + System 2 (LLM) Orchestration"
    )

    st.markdown("""
        Welcome to the **Perpetual KYC (pKYC) & Enhanced Due Diligence Simulation Sandbox**. 
        Rather than rebuilding a static, point-in-time web scraper from scratch, this prototype is an interactive 
        **Compliance Time-Machine** designed to demonstrate how AI-native due diligence platforms (like Xapien) 
        can transition from expensive one-off reports to **event-driven continuous monitoring** without bankrupting 
        compute budgets or drowning analysts in false positives.
        """)

    # Top Call-To-Action Navigation Cards
    cta_col1, cta_col2 = st.columns(2)
    with cta_col1:
        with st.container(border=True):
            st.markdown("### 🎛️ Launch the Interactive Sandbox")
            st.write(
                "Inject synthetic weekly feed deltas (or poll live UK Companies House, OpenSanctions, and GDELT data), "
                "tune Jev confidence sliders, and watch System 1 vs. System 2 unit economics in real time."
            )
            st.page_link(
                page_dashboard,
                label="Open Live Sandbox Dashboard →",
                icon="🚀",
                use_container_width=True,
            )

    with cta_col2:
        with st.container(border=True):
            st.markdown("### 🧠 Read the Product & Architecture Case Study")
            st.write(
                "Explore the initial user research on Xapien's top 5 practitioner pain points, why continuous monitoring "
                "breaks traditional LLM pipelines, and the product trade-offs behind this prototype."
            )
            st.page_link(
                page_research,
                label="Read Research & Product Decisions →",
                icon="📐",
                use_container_width=True,
            )

    st.divider()

    # How the System Works
    st.markdown("## ⚙️ How the 4-Stage Pipeline Works")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        with st.container(border=True):
            st.markdown("#### 1. Multi-Feed Delta Poll")
            st.caption("Corporate, Watchlists & News")
            st.write(
                "Monitors **UK Companies House** (filings & PSCs), **OpenSanctions** (global watchlists), "
                "and **GDELT DOC 2.0** (global adverse media) for weekly changes."
            )
    with c2:
        with st.container(border=True):
            st.markdown("#### 2. System 1 Gatekeeper")
            st.caption("TypeSafe AI's Jev (~120ms, $0.0004)")
            st.write(
                "Scores every incoming record using calibrated `Noul` (identity & novelty) and `Score` (materiality) "
                "primitives before any heavy LLM is invoked."
            )
    with c3:
        with st.container(border=True):
            st.markdown("#### 3. System 2 Synthesis")
            st.caption("Frontier LLM ($0.42/run)")
            st.write(
                "Only triggered when Jev detects a critical red flag or when a customer approves a Tier-2 material "
                "alert—synthesizing an inline-cited report upgrade (`v2`, `v3`)."
            )
    with c4:
        with st.container(border=True):
            st.markdown("#### 4. API & MCP Exposure")
            st.caption("REST + FastMCP Server")
            st.write(
                "Exposes both the versioned reports and the Jev triage queue over REST (`/api/v1/*`) and "
                "**Model Context Protocol (`/mcp/sse`)** for AI compliance agents."
            )

    st.divider()

    # Guided Demo Walkthrough
    st.markdown("## 🧪 Guided 5-Step Walkthrough (How to Test the Sandbox)")
    st.markdown("""
        Once you open the **Sandbox Dashboard**, you will see our baseline monitored entity: **Apex Global Logistics Ltd** 
        (a clean UK freight forwarder with a resolved £1,500 HMRC administrative penalty from 2024, currently at **🟢 LOW RISK `v1`**). 
        Use the **Sandbox Control Deck** in the left sidebar to test the 5 pre-built weekly scenarios in order:

        | Step | Scenario Button | What Happens Under the Hood | Business & Product Proof Point |
        | :--- | :--- | :--- | :--- |
        | **Step 1** | **1️⃣ Namesake Noise** | Injects a Miami tax fraud indictment for *Sterling Vance* (born 1991). Our UK director was born in 1978. Jev scores `Identity Match: 8%` and drops it. | **Eliminates Alert Fatigue** on common names for $0.0004 without waking the System 2 LLM. |
        | **Step 2** | **2️⃣ Routine Admin** | Injects a Companies House `AD01` office move from 10 to 14 Bishopsgate. Jev confirms identity (`99%`) and novelty (`95%`), but scores materiality at `0.28`. | **Logs silently in the audit trail** for regulatory proof without charging the customer for a new report. |
        | **Step 3** | **3️⃣ Syndicated Echo** | A freight blog re-reports the 2024 £1,500 HMRC fine already in Report `v1`. Jev compares against the baseline summary and scores `Net-New Event: 6%`. | **Solves the Syndication Echo Chamber** so customers aren't billed repeatedly for old news. |
        | **Step 4** | **4️⃣ Ambiguous Media** | Regional press alleges a customs inquiry at Port of Felixstowe. Jev scores `Worth-a-Report: 0.76`—queuing a yellow **Upsell Notification Banner**. | **Commercial Trigger:** Customer clicks *Approve & Refresh* to upgrade the report to **`v2` (🟠 HIGH RISK)**. |
        | **Step 5** | **5️⃣ Silent UBO + Sanctions** | A new PSC (*Dmitri Kovalev*) is added at Companies House, spawning a child check that hits **OpenSanctions**. Jev scores `0.97` (`>= 0.88` cutoff). | **2nd-Degree Network Catch:** Automatically triggers System 2 LLM synthesis to **`v3` (🔴 CRITICAL RISK)**. |
        """)


# =====================================================================
# PAGE 2: PRODUCT RESEARCH & ARCHITECTURE DECISIONS
# =====================================================================


def render_research_page():
    st.title("📐 Product Discovery, User Research & Architectural Decisions")
    st.caption(
        "How and why we pivoted from building a static Xapien clone to a System 1 + System 2 Continuous Monitoring Sandbox."
    )

    st.markdown("## 1. Initial Research: Top 5 Challenges Reported by Xapien Users")
    st.markdown("""
        Automated due diligence platforms have transformed point-in-time onboarding, but interviews, procurement feedback, 
        and practitioner reviews highlight five recurring operational bottlenecks:
        """)

    r1, r2 = st.columns(2)
    with r1:
        with st.container(border=True):
            st.markdown(
                "#### 1. Disambiguation Latency & False Positives on Common Names"
            )
            st.write(
                "When screening individuals with common names or generic corporate brands, scraping and evaluating "
                "hundreds of candidate records pushes generation times from 5 minutes to 20+ minutes, occasionally merging "
                "distinct individuals or dropping valid adverse media."
            )
        with st.container(border=True):
            st.markdown(
                "#### 2. Point-in-Time Snapshots vs. Continuous Monitoring (pKYC)"
            )
            st.write(
                "Running a full deep-web LLM synthesis during onboarding works well, but re-running full LLM reports across "
                "10,000 onboarded suppliers every week is economically unviable. Teams fall back to noisy legacy database alerts."
            )
        with st.container(border=True):
            st.markdown("#### 3. Lack of a Self-Serve Policy & Integration Sandbox")
            st.write(
                "Compliance teams in different sectors (e.g., iGaming vs. Private Banking vs. University Endowments) have "
                "radically different risk appetites. Users struggle to tune materiality thresholds or test API/webhook "
                "workflows without burning paid report credits."
            )

    with r2:
        with st.container(border=True):
            st.markdown("#### 4. Opaque Coverage Behind Paywalls & Offline Registries")
            st.write(
                "Expectations that an AI tool searches 'the whole internet' clash with hard financial journalism paywalls, "
                "CAPTCHA-protected court portals, and non-digitized offshore registries."
            )
        with st.container(border=True):
            st.markdown("#### 5. Audit Fatigue & Context Overload on Large Entities")
            st.write(
                "While inline citations prevent hallucinations, dossiers on large multinationals or public figures "
                "surface dozens of repetitive regulatory stories, forcing analysts to click through every link to verify "
                "materiality for MLRO sign-off."
            )

    st.divider()

    st.markdown(
        "## 2. Key Product Decision: Why Build a 'Controlled Sandbox' Instead of a Full Scraper?"
    )
    st.info(
        "**Product Insight:** If you build a prototype tied solely to live external feeds, you cannot reliably demonstrate "
        "continuous monitoring—because you would have to wait weeks for a real company to get sanctioned or sued during a demo. "
        "By building a **Dual-Mode Simulation Sandbox** (combining deterministic scenario injection with live open-data adapters), "
        "we directly solve User Challenge #2 (Continuous Monitoring) and User Challenge #3 (Self-Serve Policy Tuning Sandbox)."
    )

    st.markdown(
        "## 3. Architectural Decision: Why Pair System 1 (Jev) with System 2 (Frontier LLM)?"
    )
    st.markdown("""
        In an event-driven monitoring product, 95%+ of weekly feed deltas are **noise** (namesakes, syndicated re-prints of old news, 
        or routine corporate filings). 

        | Metric | Naive All-LLM Pipeline (System 2 Only) | Hybrid Gatekeeper Pipeline (Jev System 1 + LLM System 2) |
        | :--- | :--- | :--- |
        | **Triage Latency per Record** | 3.5 – 8.0 seconds | **~120 milliseconds** |
        | **Cost per Delta Evaluated** | ~$0.05 – $0.42 | **$0.0004** (100x–1000x cheaper) |
        | **Probability Calibration** | Poor (verbalized confidence is uncalibrated) | **Calibrated distribution** over `Noul`, `Choice`, and `Score` |
        | **Policy Tunability** | Requires prompt re-engineering & re-running LLM | **Instant slider adjustment** against numeric probability cutoffs |

        ### How the Jev Gatekeeper Evaluates Every Delta in a Single Pass:
        1. **Gate 1 – Identity Match (`Noul`):** *"Does `incoming_delta` refer to the exact `monitored_entity` or its `known_officers`?"* (Filters out namesake noise immediately).
        2. **Gate 2 – Novelty Check (`Noul`):** *"Does `incoming_delta` describe a net-new event NOT already covered in `baseline_risk_summary`?"* (Prevents paying twice when 15 blogs syndicate last year's fine).
        3. **Gate 3 – Risk Categorization (`Choice`):** Classifies the delta into `Sanctions_PEP`, `Financial_Crime`, `Corporate_UBO_Change`, `ESG_Reputational`, or `Routine_Admin`.
        4. **Gate 4 – Regeneration Urgency (`Score`):** Produces a calibrated **Worth-a-Report Score (`0.00 – 1.00`)** that drives commercial routing:
           * `< 0.65`: Log silently in audit trail (zero LLM cost).
           * `0.65 – 0.87`: **Upsell Notification** — Notify customer or AI agent via MCP that a refreshed report is recommended.
           * `>= 0.88`: **Critical Auto-Regeneration** — Automatically wakes the System 2 LLM to synthesize a new report version.
        """)

    st.markdown(
        "### Sandbox Architecture Diagram (System 1 + System 2 + FastMCP + Streamlit)"
    )

    mermaid_sandbox_architecture = """flowchart TB
        %% Styling
        classDef external fill:#1e293b,stroke:#64748b,stroke-width:1.5px,color:#f8fafc
        classDef simulator fill:#312e81,stroke:#818cf8,stroke-width:1.5px,color:#f8fafc
        classDef system1 fill:#065f46,stroke:#34d399,stroke-width:2px,color:#f8fafc
        classDef system2 fill:#7c2d12,stroke:#fb923c,stroke-width:2px,color:#f8fafc
        classDef storage fill:#3b0764,stroke:#c084fc,stroke-width:1.5px,color:#f8fafc
        classDef consumer fill:#0f172a,stroke:#38bdf8,stroke-width:1.5px,color:#f8fafc
    
        %% Subgraph 1: Ingestion & Trigger Layer
        subgraph Ingestion ["1. Dual-Mode Feed Ingestion Layer"]
            direction TB
            subgraph LiveFeeds ["Live Open-Data Adapters (live_feeds.py)"]
                CH["🏢 UK Companies House API<br/>(Profile, Filings, PSCs/UBOs)"]:::external
                OS["🚨 OpenSanctions API<br/>(/match Watchlists & PEPs)"]:::external
                GDELT["📰 GDELT DOC 2.0 API<br/>(Global Adverse Media)"]:::external
                CH -. "2nd-Degree UBO Spawn" .-> OS
            end
    
            subgraph TimeMachine ["Sandbox Time-Machine (Deterministic)"]
                Presets["⚡ 5 Synthetic Event Presets<br/>1. Namesake Noise (DOB mismatch)<br/>2. Routine Admin (AD01 move)<br/>3. Syndicated Echo (Duplicate)<br/>4. Ambiguous Media (Port probe)<br/>5. Silent UBO + OFAC Hit"]:::simulator
                Cron["⏰ Modal Cron Trigger<br/>(Monday 06:00 UTC Pulse)"]:::simulator
            end
        end
    
        %% Subgraph 2: Core Modal Container
        subgraph ModalCloud ["2. Modal Serverless Runtime (sandbox_server.py)"]
            direction TB
            Normalizer["📥 FeedRecord Normalizer<br/>(Unified Schema + Baseline Context)"]
    
            subgraph JevEngine ["System 1 Gatekeeper: TypeSafe AI Jev (~120ms | $0.0004)"]
                direction LR
                G1["Gate 1: Identity Match<br/>(Noul >= 0.65)"]:::system1
                G2["Gate 2: Net-New Event<br/>(Noul >= 0.50)"]:::system1
                G3["Gate 3: Risk Category<br/>(Choice Primitive)"]:::system1
                G4["Gate 4: Worth-a-Report<br/>(Calibrated Score 0.0–1.0)"]:::system1
                G1 --> G2 --> G3 --> G4
            end
    
            Router{"🚦 Policy Threshold Router"}
    
            Discard["🛑 Discard & Audit Log<br/>(False Positive / Syndicated Echo)<br/>LLM Cost: $0.00"]
            SilentLog["📝 Append Admin Delta<br/>(Score < 0.65)<br/>LLM Cost: $0.00"]
            TriageQueue["⚠️ Pending Triage Queue<br/>(0.65 <= Score < 0.88)<br/>Upsell Notification Sent"]
    
            subgraph System2Engine ["System 2 Synthesis Engine ($0.42/run)"]
                LLM["🧠 Frontier LLM<br/>(Inline-Cited Report Synthesis<br/>Upgrades Report v1 -> v2 -> v3)"]:::system2
            end
    
            StateStore[("🗄️ modal.Dict Store<br/>(Entities, Versioned Reports,<br/>Audit Stream, Policy Cutoffs)")]:::storage
        end
    
        %% Subgraph 3: Exposure & Consumption Layer
        subgraph Interfaces ["3. Exposure & Client Interfaces"]
            direction TB
            StreamlitUI["🎛️ Multi-Page Streamlit App<br/>(Overview, Research Case Study,<br/>Live Control Deck & Sliders)"]:::consumer
            RestAPI["🔌 FastAPI REST Endpoints<br/>(/api/v1/entities, /inject-delta,<br/>/poll-live-feeds, /approve-refresh)"]:::consumer
            MCPServer["🤖 FastMCP Server (/mcp/sse)<br/>Resources: dd://latest-report, dd://triage-queue<br/>Tools: simulate_event, approve_refresh"]:::consumer
            Agents["💻 External AI Agents & Systems<br/>(Claude Desktop, Cursor, Gemini CLI,<br/>Enterprise GRC Webhooks)"]:::consumer
        end
    
        %% Connections
        CH & OS & GDELT --> Normalizer
        Presets --> Normalizer
        Cron -. "Triggers Weekly Poll" .-> LiveFeeds
    
        Normalizer --> JevEngine
        G4 --> Router
    
        Router -- "Identity < 0.65 or<br/>Novelty < 0.50" --> Discard
        Router -- "Score < 0.65" --> SilentLog
        Router -- "0.65 <= Score < 0.88<br/>(Tier 2 Alert)" --> TriageQueue
        Router -- "Score >= 0.88<br/>(Tier 3 Critical)" --> LLM
    
        Discard & SilentLog --> StateStore
        TriageQueue --> StateStore
        TriageQueue -- "User / Agent Approves<br/>Report Refresh" --> LLM
        LLM -- "Writes New Report Version" --> StateStore
    
        StateStore <--> RestAPI
        StateStore <--> MCPServer
        RestAPI <--> StreamlitUI
        RestAPI <--> Agents
        MCPServer <--> Agents"""

    st_mermaid(mermaid_sandbox_architecture, height=800)

    st.divider()

    st.markdown(
        "### Continuous Monitoring Sequence Diagram (System 1 vs. System 2 Flow)"
    )

    mermaid_continuous_monitoring = """sequenceDiagram
    autonumber
    actor User as Compliance Analyst / AI Agent (MCP)
    participant UI as Sandbox Control Deck / Cron
    participant Feeds as Open Feeds (CH / OpenSanctions / GDELT)
    participant Server as FastAPI + FastMCP Orchestrator
    participant Jev as TypeSafe AI Jev (System 1)
    participant LLM as Frontier LLM (System 2)

    Note over User,LLM: Path A: Weekly Noise / Echo (95% of Real-World Events)
    UI->>Server: Inject Scenario 1 (Namesake) or Scenario 3 (Old News Echo)
    Server->>Jev: Evaluate State (Baseline Summary + Officer DOBs + Delta)
    Jev-->>Server: Noul Identity: 0.08 (or Novelty: 0.06) | Score: 0.04 ($0.0004)
    Server->>Server: Log in Audit Stream as DISCARDED (Zero LLM Spend)
    Server-->>User: Telemetry Updated ($0.42 Saved)

    Note over User,LLM: Path B: Ambiguous Adverse Media (Commercial Upsell Flow)
    UI->>Server: Inject Scenario 4 (Felixstowe Port Probe Rumor)
    Server->>Jev: Evaluate State + Client Policy Thresholds
    Jev-->>Server: Identity: 0.87 | Novelty: 0.94 | Worth-a-Report Score: 0.76
    Server->>Server: Score >= 0.65 Notify Cutoff -> Push to Triage Queue
    Server-->>User: 🔔 Alert via UI Banner & MCP Resource (dd://monitoring/triage-queue)
    User->>Server: Approve Report Refresh (POST /approve-refresh or MCP Tool)
    Server->>LLM: Synthesize Baseline v1 + Approved Delta with Inline Citations
    LLM-->>Server: Return Report v2 (🟠 HIGH RISK) ($0.42)
    Server-->>User: Display Upgraded Report v2 + Audit Trail

    Note over User,LLM: Path C: 2nd-Degree UBO Swap + Sanctions Hit (Critical Auto-Regen)
    UI->>Feeds: Poll Live Feeds / Inject Scenario 5 (New PSC: Dmitri Kovalev)
    Feeds->>Feeds: Companies House PSC01 Spawns Child OpenSanctions Query
    Feeds-->>Server: Return OFAC SDN & UK Sanctions Match Record
    Server->>Jev: Evaluate Delta against Policy
    Jev-->>Server: Identity: 0.97 | Novelty: 0.99 | Worth-a-Report Score: 0.97
    Server->>LLM: Score >= 0.88 Auto-Regen Cutoff -> Immediately Trigger System 2
    LLM-->>Server: Return Report v3 (🔴 CRITICAL RISK)
    Server-->>User: 🚨 Immediate MLRO Escalation + Report v3 Ready"""

    st_mermaid(mermaid_continuous_monitoring, height=800)

    st.divider()

    st.markdown("## 4. Data Source & Infrastructure Decisions")
    d1, d2 = st.columns(2)
    with d1:
        st.markdown("""
            #### Open Data Trilogy (Zero Enterprise Licensing Cost)
            * **Corporate & UBO Structure:** **UK Companies House REST API** — Provides real-time filing history deltas and Persons with Significant Control (PSCs) to demonstrate 2nd-degree network drift.
            * **Watchlists & PEPs:** **OpenSanctions `/match` API** — Consolidates 80+ global sanctions and PEP lists so newly discovered PSCs from Companies House are automatically screened.
            * **Adverse Media:** **GDELT DOC 2.0 API** — Free, real-time global news indexing across 100+ languages.
            """)
    with d2:
        st.markdown("""
            #### Why Modal + FastMCP Over Edge Workers
            * **Zero Rewrite Overhead:** Hosting FastAPI, FastMCP, and Streamlit together inside a unified **Modal** container avoids Cloudflare Workers' 10ms CPU cap and WebAssembly constraints while staying well within Modal's $30/month free credit tier.
            * **Agent-Ready via MCP:** Exposing `dd://entities/{id}/latest-report` and `dd://monitoring/triage-queue` via **FastMCP** allows compliance officers to query and approve report refreshes directly from Claude, Cursor, or Gemini CLI.
            """)

    st.page_link(
        page_dashboard,
        label="Test These Decisions in the Live Sandbox Dashboard →",
        icon="🎛️",
        use_container_width=True,
    )


# =====================================================================
# PAGE 3: INTERACTIVE SANDBOX DASHBOARD
# =====================================================================


def render_dashboard_page():
    entities_map = api_get_entities()
    if st.session_state["active_entity_id"] not in entities_map:
        st.session_state["active_entity_id"] = "ent_apex_01"

    ENTITY_ID = st.session_state["active_entity_id"]
    report, stream_data = api_get_state(ENTITY_ID)
    policy = stream_data["active_policy"]
    telemetry = stream_data["telemetry"]
    pending_queue = stream_data["pending_approval_queue"]
    audit_events = stream_data["audit_event_stream"]

    # Sidebar Controls (Only rendered when on the Dashboard page)

    # =====================================================================
    # SIDEBAR: ENTITY SWITCHER, SANDBOX INJECTOR, LIVE POLL & SLIDERS
    # =====================================================================

    with st.sidebar:
        st.title("🎛️ Sandbox Control Deck")

        # Entity Selector
        entity_options = list(entities_map.keys())
        selected_eid = st.selectbox(
            "Monitored Entity",
            options=entity_options,
            index=entity_options.index(ENTITY_ID),
            format_func=lambda eid: f"{entities_map[eid]['name']} ({eid})",
        )
        if selected_eid != ENTITY_ID:
            st.session_state["active_entity_id"] = selected_eid
            st.rerun()

        # Live Open-Data Controls
        st.subheader("🌐 Live Open-Data Feeds")
        if st.button(
            "📡 Poll Live Feeds Now (GDELT/CH/OS)",
            use_container_width=True,
            help="Fetches real-time deltas from GDELT DOC 2.0, UK Companies House, and OpenSanctions",
        ):
            with st.spinner(
                "Polling live GDELT, Companies House & OpenSanctions APIs..."
            ):
                res = api_poll_live_feeds(ENTITY_ID, timespan="1m")
            st.toast(
                f"Polled {res['polled_records_count']} live records through Jev!",
                icon="🌐",
            )
            st.rerun()

        with st.expander("🔍 Onboard Real UK Company (Live)"):
            live_name = st.text_input("Company Name", "Tesco PLC")
            live_num = st.text_input("UK Company Number (Optional)", "00445790")
            if st.button("Run Live Onboarding", use_container_width=True):
                with st.spinner(f"Running live sweep on {live_name}..."):
                    created = api_onboard_live(live_name, live_num)
                    st.session_state["active_entity_id"] = created["entity_id"]
                st.rerun()

        st.divider()

        st.subheader("⚡ Simulate Weekly Scenario")
        if st.button("1️⃣ Namesake Noise (Florida Fraud)", use_container_width=True):
            api_inject_scenario(ENTITY_ID, "1_namesake_noise")
            st.rerun()
        if st.button("2️⃣ Routine Admin (Address Move)", use_container_width=True):
            api_inject_scenario(ENTITY_ID, "2_routine_admin")
            st.rerun()
        if st.button("3️⃣ Syndicated Echo (Old 2024 Fine)", use_container_width=True):
            api_inject_scenario(ENTITY_ID, "3_syndicated_echo")
            st.rerun()
        if st.button("4️⃣ Ambiguous Media (Port Probe)", use_container_width=True):
            api_inject_scenario(ENTITY_ID, "4_ambiguous_media")
            st.rerun()
        if st.button(
            "5️⃣ Silent UBO Swap + Sanctions Hit",
            use_container_width=True,
            type="primary",
        ):
            api_inject_scenario(ENTITY_ID, "5_silent_ubo_sanctions")
            st.rerun()

        with st.expander("➕ Inject Custom Delta Event"):
            custom_feed = st.selectbox(
                "Feed Source",
                ["GDELT_ADVERSE_MEDIA", "COMPANIES_HOUSE", "OPENSANCTIONS"],
            )
            custom_url = st.text_input(
                "Source URL", "https://ft.example.com/2026/investigation"
            )
            custom_text = st.text_area(
                "Raw Snippet Content",
                f"{stream_data['name']} named in customs tariff evasion briefing.",
            )
            if st.button("Inject Custom Event", use_container_width=True):
                api_inject_scenario(
                    ENTITY_ID,
                    custom_record={
                        "source_feed": custom_feed,
                        "url": custom_url,
                        "raw_content": custom_text,
                    },
                )
                st.rerun()

        st.divider()

        st.subheader("🎚️ Jev System 1 Policy Sliders")
        with st.form("policy_form"):
            new_disambig = st.slider(
                "Entity Match Cutoff (Jev Noul)",
                0.0,
                1.0,
                float(policy["disambiguation_cutoff"]),
                0.05,
                help="Minimum probability that the record refers to our exact target entity.",
            )
            new_novelty = st.slider(
                "Net-New Event Cutoff (Jev Noul)",
                0.0,
                1.0,
                float(policy["novelty_cutoff"]),
                0.05,
                help="Minimum probability that the event is not already covered in the current report.",
            )
            new_notify = st.slider(
                "Upsell / Notify Threshold (Jev Score)",
                0.0,
                1.0,
                float(policy["notify_threshold"]),
                0.05,
                help="Score above which the customer is notified to approve a report refresh.",
            )
            new_autoregen = st.slider(
                "Critical Auto-Regen Threshold (Jev Score)",
                0.0,
                1.0,
                float(policy["auto_regen_threshold"]),
                0.05,
                help="Score above which System 2 LLM automatically regenerates the report.",
            )
            if st.form_submit_button("Update Jev Thresholds", use_container_width=True):
                api_update_policy(
                    {
                        "sector": policy["sector"],
                        "risk_appetite": policy["risk_appetite"],
                        "disambiguation_cutoff": new_disambig,
                        "novelty_cutoff": new_novelty,
                        "notify_threshold": new_notify,
                        "auto_regen_threshold": new_autoregen,
                    }
                )
                st.toast("Policy thresholds updated!", icon="✅")
                st.rerun()

        st.divider()
        if st.button("🔄 Reset Sandbox to v1 Baseline", use_container_width=True):
            api_reset_sandbox()
            st.rerun()

    # =====================================================================
    # MAIN STAGE HEADER & TELEMETRY KPI BAR
    # =====================================================================

    RISK_BADGE_MAP = {
        "LOW": "🟢 LOW RISK",
        "MEDIUM": "🟡 MEDIUM RISK",
        "HIGH": "🟠 HIGH RISK",
        "CRITICAL": "🔴 CRITICAL RISK",
    }

    head_col1, head_col2 = st.columns([3, 1])
    with head_col1:
        st.title(f"🛡️ {stream_data['name']}")
        st.markdown(
            f"**Co. Number:** `{stream_data['company_number']}` | **Jurisdiction:** `{stream_data['jurisdiction']}` | "
            f"**Active Report Version:** `v{report['version']}`"
        )
    with head_col2:
        st.metric(
            label="Current Calibrated Risk",
            value=RISK_BADGE_MAP.get(
                report["overall_risk_level"], report["overall_risk_level"]
            ),
            delta=f"Jev Score: {report['jev_calibrated_risk_score']:.2f}",
            delta_color="inverse",
        )

    st.divider()

    # Telemetry & Unit Economics Bar
    st.subheader(
        "📊 Continuous Monitoring Telemetry & Unit Economics (System 1 vs. System 2)"
    )
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric("Deltas Scanned", telemetry["total_deltas_evaluated"])
    kpi2.metric(
        "Filtered by Jev (System 1)",
        telemetry["filtered_by_jev_system1"],
        help="Events handled for $0.0004 without waking the LLM",
    )
    kpi3.metric(
        "LLM Report Regenerations",
        telemetry["system2_llm_regenerations"],
        help="Full System 2 synthesis runs ($0.42/run)",
    )
    kpi4.metric(
        "Actual Compute Spend",
        f"${telemetry['actual_compute_spend_usd']:.4f}",
        delta=f"vs ${telemetry['naive_always_llm_spend_usd']:.2f} Naive LLM",
        delta_color="normal",
    )
    kpi5.metric(
        "Net Cost Saved by Jev",
        f"${telemetry['estimated_cost_savings_usd']:.4f}",
        delta="System 1 Gatekeeper ROI",
    )

    # =====================================================================
    # TRIAGE ALERT BANNER (IF TIER-2 MATERIAL EVENTS ARE PENDING)
    # =====================================================================

    if pending_queue:
        st.warning(
            f"🔔 **{len(pending_queue)} Material Update(s) Flagged by Gatekeeper!** "
            "These events exceeded your Notification Threshold but are below the Auto-Regeneration cutoff."
        )
        for p_evt in pending_queue:
            ev = p_evt["jev_evaluation"]
            rec = p_evt["record"]
            col_alert, col_btn = st.columns([4, 1])
            with col_alert:
                st.markdown(
                    f"* **[{rec['source_feed']}]** {rec['raw_content']}  \n"
                    f"  *Jev Worth-a-Report Score:* **`{ev['worth_a_report_score']:.2f}`** | "
                    f"*Identity Match:* `{ev['is_same_entity_prob']:.2f}` | *Novelty:* `{ev['is_net_new_event_prob']:.2f}`"
                )
            with col_btn:
                if st.button(
                    "⚡ Approve & Refresh ($0.42)",
                    key=p_evt["event_id"],
                    type="primary",
                    use_container_width=True,
                ):
                    api_approve_refresh(ENTITY_ID)
                    st.toast("System 2 LLM synthesized updated report!", icon="🚀")
                    st.rerun()

    st.divider()

    # =====================================================================
    # MAIN WORKSPACE: LIVE REPORT (LEFT) & JEV AUDIT STREAM (RIGHT)
    # =====================================================================

    left_pane, right_pane = st.columns([1.15, 1])

    with left_pane:
        st.subheader(f"📄 Due Diligence Report (Version v{report['version']})")
        st.caption(
            f"Report ID: `{report['report_id']}` • Generated: `{report['generated_at'][:19]} UTC`"
        )

        st.markdown("#### Executive Summary")
        st.info(report["executive_summary"])

        tab_corp, tab_sanc, tab_media, tab_cite = st.tabs(
            [
                "🏢 Corporate & UBO",
                "🚨 Sanctions & PEPs",
                "📰 Adverse Media",
                f"🔗 Audit Citations ({len(report['audit_citations'])})",
            ]
        )
        with tab_corp:
            for item in report["corporate_structure_findings"]:
                st.markdown(f"- {item}")
        with tab_sanc:
            for item in report["sanctions_and_peps_findings"]:
                if "CRITICAL" in item:
                    st.error(item)
                else:
                    st.markdown(f"- {item}")

        with tab_media:
            for item in report["adverse_media_findings"]:
                st.markdown(f"- {item}")
        with tab_cite:
            for cite in report["audit_citations"]:
                st.markdown(
                    f"**`[{cite['id']}]`** **{cite['source_feed']}** ({cite['timestamp'][:10]})  \n"
                    f"{cite['raw_content']} — [Source Link]({cite['url']})"
                )

    with right_pane:
        st.subheader("🔬 System 1 Gatekeeper Audit Log")
        st.caption(
            "Every weekly delta is scored for Identity, Novelty, and Materiality (~120ms, $0.0004)."
        )

        if not audit_events:
            st.info(
                "Use the sidebar to inject synthetic scenarios or poll live GDELT/Companies House feeds."
            )
        else:
            # Show newest events at the top
            for evt in reversed(audit_events):
                ev = evt["jev_evaluation"]
                rec = evt["record"]
                action = ev["action_taken"]

                ACTION_ICON = {
                    "DISCARDED_FALSE_POSITIVE": "🛑",
                    "DISCARDED_DUPLICATE_ECHO": "♻️",
                    "LOGGED_SILENT_ADMIN_DELTA": "📝",
                    "QUEUED_FOR_USER_APPROVAL": "⚠️",
                    "AUTO_TRIGGERED_REPORT_REFRESH": "🚨",
                }.get(action, "ℹ️")

                with st.expander(
                    f"{ACTION_ICON} {action} | Score: {ev['worth_a_report_score']:.2f} ({rec['source_feed']})",
                    expanded=True,
                ):
                    st.markdown(f"**Snippet:** {rec['raw_content']}")
                    st.caption(
                        f"Scenario: `{evt['scenario_name']}` | Source URL: {rec['url']}"
                    )

                    m1, m2, m3 = st.columns(3)
                    m1.metric("1. Identity Match", f"{ev['is_same_entity_prob']:.0%}")
                    m2.metric("2. Net-New Event", f"{ev['is_net_new_event_prob']:.0%}")
                    m3.metric("3. Worth-a-Report", f"{ev['worth_a_report_score']:.2f}")
                    st.caption(
                        f"Category: `{ev['risk_category']}` • {ev['reasoning_note']}"
                    )


# =====================================================================
# MULTI-PAGE NAVIGATION ROUTER
# =====================================================================

page_home = st.Page(render_home_page, title="Overview & Guide", icon="🏠", default=True)
page_dashboard = st.Page(
    render_dashboard_page, title="Live Sandbox Dashboard", icon="🎛️"
)
page_research = st.Page(
    render_research_page, title="Research & Product Decisions", icon="📐"
)

nav = st.navigation({"pKYC Prototype": [page_home, page_dashboard, page_research]})
nav.run()
