"""
End-to-end test and interactive verification script for the Xapien + Jev pKYC FastMCP Server.

Usage:
  1. Run unit/ASGI transport security + SSE handshake tests (no separate server process needed):
       uv run python test_mcp_client.py --self-test

  2. Test against a running local server (http://127.0.0.1:8000/mcp/sse):
       uv run python test_mcp_client.py

  3. Test against the deployed Modal endpoint:
       uv run python test_mcp_client.py --url https://mrmunro--munron-pkyc-sandbox-api.us-east.modal.run/mcp/sse
"""

import argparse
import asyncio
import json
import os
import sys
import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client


DEFAULT_MCP_URL = os.getenv("SANDBOX_MCP_URL", "http://127.0.0.1:8000/mcp/sse")
MODAL_MCP_URL = "https://mrmunro--munron-pkyc-sandbox-api.us-east.modal.run/mcp/sse"


async def verify_host_header_security() -> None:
    """
    Verifies directly against the FastAPI + FastMCP ASGI app that:
      1. Requests with the whitelisted Modal Host header do NOT fail with HTTP 421.
      2. Requests with localhost / 127.0.0.1 do NOT fail with HTTP 421.
      3. Requests with an untrusted Host header ARE blocked with HTTP 421 (DNS rebinding protection active).
    """
    from sandbox_server import app, MODAL_API_HOST

    print("=== 1. Verifying MCP TransportSecuritySettings (DNS Rebinding Protection) ===")
    transport = httpx.ASGITransport(app=app)

    # Check 1: Untrusted host MUST be rejected with 421
    async with httpx.AsyncClient(
        transport=transport, base_url="http://evil-rebind.example.com"
    ) as client:
        resp = await client.post(
            "/mcp/messages/?session_id=test",
            json={},
        )
        assert resp.status_code == 421, (
            f"Expected HTTP 421 for untrusted host, got {resp.status_code}: {resp.text}"
        )
        print(
            f"  [PASS] Untrusted host ('evil-rebind.example.com') rejected with HTTP {resp.status_code} ({resp.text})"
        )

    # Check 2: Whitelisted Modal host MUST pass host validation (returns 400 invalid session_id, NOT 421)
    async with httpx.AsyncClient(
        transport=transport,
        base_url=f"https://{MODAL_API_HOST}",
        headers={
            "Host": MODAL_API_HOST,
            "Origin": f"https://{MODAL_API_HOST}",
        },
    ) as client:
        resp = await client.post(
            "/mcp/messages/?session_id=nonexistent",
            json={},
        )
        assert resp.status_code != 421, (
            f"Modal host '{MODAL_API_HOST}' was unexpectedly rejected with HTTP 421: {resp.text}"
        )
        print(
            f"  [PASS] Whitelisted Modal host ('{MODAL_API_HOST}') passed TransportSecurityMiddleware (status {resp.status_code}, not 421)"
        )

    # Check 3: Localhost with port MUST pass host validation (not 421)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8000",
        headers={"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"},
    ) as client:
        resp = await client.post(
            "/mcp/messages/?session_id=nonexistent",
            json={},
        )
        assert resp.status_code != 421, (
            f"Localhost '127.0.0.1:8000' was unexpectedly rejected with HTTP 421: {resp.text}"
        )
        print(
            f"  [PASS] Localhost ('127.0.0.1:8000') passed TransportSecurityMiddleware (status {resp.status_code}, not 421)"
        )


async def run_mcp_session_checks(url: str) -> None:
    """Connects to the MCP SSE endpoint using the official MCP client and exercises resources & tools."""
    print(f"\n=== Connecting MCP SSE Client to: {url} ===")
    async with sse_client(url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            init_result = await session.initialize()
            print(
                f"  [PASS] Handshake initialized with server: {init_result.server_info.name} (v{init_result.server_info.version})"
            )

            # 1. List Tools
            tools_res = await session.list_tools()
            tool_names = [t.name for t in tools_res.tools]
            print(f"  [PASS] Discovered {len(tool_names)} MCP Tools: {tool_names}")

            # 2. List Resources & Resource Templates
            resources_res = await session.list_resources()
            res_uris = [str(r.uri) for r in resources_res.resources]
            templates_res = await session.list_resource_templates()
            template_uris = [
                str(rt.uri_template) for rt in templates_res.resource_templates
            ]
            print(f"  [PASS] Discovered Static Resources: {res_uris}")
            print(f"  [PASS] Discovered Resource Templates: {template_uris}")

            # 3. Read baseline report resource
            report_res = await session.read_resource(
                "dd://entities/ent_apex_01/latest-report"
            )
            report_json = json.loads(report_res.contents[0].text)
            print(
                f"  [PASS] Read dd://entities/ent_apex_01/latest-report -> version v{report_json['version']} ({report_json['overall_risk_level']})"
            )

            # 4. Call simulate_monitoring_event tool (Scenario 4: Ambiguous Media -> queues for approval)
            sim_res = await session.call_tool(
                "simulate_monitoring_event",
                arguments={
                    "scenario_preset": "4_ambiguous_media",
                    "entity_id": "ent_apex_01",
                },
            )
            sim_payload = json.loads(sim_res.content[0].text)
            action_taken = sim_payload["event"]["jev_evaluation"]["action_taken"]
            score = sim_payload["event"]["jev_evaluation"]["worth_a_report_score"]
            print(
                f"  [PASS] Tool simulate_monitoring_event('4_ambiguous_media') -> action={action_taken}, score={score}"
            )

            # 5. Read triage queue resource
            queue_res = await session.read_resource("dd://monitoring/triage-queue")
            queue_json = json.loads(queue_res.contents[0].text)
            pending_count = len(
                queue_json.get("ent_apex_01", {}).get("pending_events", [])
            )
            print(
                f"  [PASS] Read dd://monitoring/triage-queue -> {pending_count} pending event(s) for ent_apex_01"
            )

            # 6. Call approve_report_refresh tool
            approve_res = await session.call_tool(
                "approve_report_refresh",
                arguments={"entity_id": "ent_apex_01"},
            )
            approve_payload = json.loads(approve_res.content[0].text)
            print(
                f"  [PASS] Tool approve_report_refresh('ent_apex_01') -> {approve_payload.get('status')}"
            )


async def run_self_test() -> None:
    """Spins up uvicorn on a free local port, runs host security checks and full MCP SSE session checks."""
    import socket
    import uvicorn
    from sandbox_server import app, STORE

    await verify_host_header_security()
    await STORE.clear_and_seed()

    # Bind a free local port and test full SSE lifecycle
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    # Wait for server startup
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        await run_mcp_session_checks(f"http://127.0.0.1:{port}/mcp/sse")
    finally:
        await STORE.clear_and_seed()
        server.should_exit = True
        await server_task


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test the Xapien + Jev pKYC MCP Server locally or on Modal."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_MCP_URL,
        help=f"Target MCP SSE URL (default: {DEFAULT_MCP_URL})",
    )
    parser.add_argument(
        "--modal",
        action="store_true",
        help=f"Shortcut to test the deployed Modal URL ({MODAL_MCP_URL})",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run in-process TransportSecurity (421) checks + spin up a temporary local server for end-to-end SSE testing",
    )
    args = parser.parse_args()

    try:
        if args.self_test:
            asyncio.run(run_self_test())
        else:
            target_url = MODAL_MCP_URL if args.modal else args.url
            asyncio.run(run_mcp_session_checks(target_url))
        print("\nAll MCP verification checks passed successfully!")
    except Exception as exc:
        import traceback

        traceback.print_exc()
        print(f"\n[FAIL] MCP verification failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
