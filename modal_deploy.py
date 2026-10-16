import os
import subprocess
import modal

app = modal.App("munron-pkyc-sandbox")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi", "uvicorn", "fastmcp", "httpx", "pydantic", "streamlit", "pandas"
    )
    .add_local_python_source("sandbox_server", "live_feeds", "sandbox_dashboard")
)

# Optional Modal Secret for Live Jev API, UK Companies House, and OpenSanctions keys:
# Create once via CLI:
#   modal secret create xapien-sandbox-secrets \
#     TYPESAFE_API_KEY="your_jev_key" \
#     COMPANIES_HOUSE_API_KEY="your_ch_key" \
#     OPENSANCTIONS_API_KEY="your_os_key"
# Then set USE_MODAL_SECRETS=1 when deploying, or uncomment the secret below.
SANDBOX_SECRETS = (
    [modal.Secret.from_name("xapien-sandbox-secrets")]
    if os.getenv("USE_MODAL_SECRETS") == "1"
    else []
)


# 1. Public REST API (/docs, /api/v1/*) + FastMCP Endpoint (/mcp/sse)
@app.function(image=image, secrets=SANDBOX_SECRETS, scaledown_window=120)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def api():
    from sandbox_server import app as fastapi_app

    return fastapi_app


# 2. Public Streamlit Dashboard UI (Dynamically discovers the `api` Modal URL)
@app.function(
    image=image,
    max_containers=1,  # Sticky session for Streamlit WebSockets
    scaledown_window=300,
)
@modal.concurrent(max_inputs=50)
@modal.web_server(8501)
def dashboard():
    # Dynamically resolve the live Modal HTTPS URL of the `api` function above
    api_root_url = api.get_web_url().rstrip("/")

    env = os.environ.copy()
    env["SANDBOX_API_BASE"] = f"{api_root_url}/api/v1"
    env["SANDBOX_MCP_URL"] = f"{api_root_url}/mcp/sse"
    env["SANDBOX_DOCS_URL"] = f"{api_root_url}/docs"

    subprocess.Popen(
        [
            "streamlit",
            "run",
            "sandbox_dashboard.py",
            "--server.port",
            "8501",
            "--server.address",
            "0.0.0.0",
            "--server.headless",
            "true",
            "--server.enableCORS",
            "false",
            "--server.enableXsrfProtection",
            "false",
        ],
        env=env,
    )


# 3. Weekly Continuous Monitoring Pulse (Every Monday at 06:00 UTC)
@app.function(image=image, secrets=SANDBOX_SECRETS, schedule=modal.Cron("0 6 * * 1"))
async def weekly_pkyc_pulse():
    from sandbox_server import STORE, poll_live_entity_feeds

    await STORE.load_or_seed()
    for entity_id in list(STORE.entities.keys()):
        res = await poll_live_entity_feeds(entity_id=entity_id, timespan="1w")
        print(
            f"[Weekly pKYC Pulse] Entity {entity_id}: {res['polled_records_count']} live records evaluated by Gatekeeper."
        )
