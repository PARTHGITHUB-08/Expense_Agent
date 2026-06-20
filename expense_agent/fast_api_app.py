import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from expense_agent.agent import root_agent
from expense_agent.app_utils.telemetry import setup_telemetry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

setup_telemetry(otel_to_cloud=False)

fastapi_app = FastAPI(title="Ambient Expense Agent", version="0.1.0")


@fastapi_app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ambient Expense Agent</title>
    <style>
        :root {
            --bg: #07111f;
            --panel: rgba(12, 21, 38, 0.86);
            --panel-2: rgba(19, 32, 56, 0.9);
            --text: #e8eefc;
            --muted: #9fb0cf;
            --accent: #6ee7c8;
            --accent-2: #7aa7ff;
            --shadow: 0 30px 80px rgba(0,0,0,0.35);
            --radius: 22px;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
            color: var(--text);
            background:
                radial-gradient(circle at top left, rgba(110,231,200,0.18), transparent 30%),
                radial-gradient(circle at top right, rgba(122,167,255,0.20), transparent 28%),
                linear-gradient(160deg, #050b15 0%, #0b1527 52%, #07111f 100%);
        }
        .shell { max-width: 1180px; margin: 0 auto; padding: 32px 20px 48px; }
        .hero { display: grid; gap: 24px; grid-template-columns: 1.15fr 0.85fr; align-items: stretch; }
        .card {
            background: var(--panel);
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow: var(--shadow);
            border-radius: var(--radius);
            backdrop-filter: blur(18px);
        }
        .brand, .form-panel { padding: 30px; }
        .brand { position: relative; overflow: hidden; }
        .brand::after {
            content: "";
            position: absolute;
            inset: auto -10% -35% auto;
            width: 280px;
            height: 280px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(110,231,200,0.25), transparent 66%);
            pointer-events: none;
        }
        .eyebrow { text-transform: uppercase; letter-spacing: 0.22em; color: var(--accent); font-size: 0.78rem; margin-bottom: 14px; }
        h1 { margin: 0; font-size: clamp(2.6rem, 5vw, 4.8rem); line-height: 0.95; letter-spacing: -0.06em; max-width: 10ch; }
        .lede { margin: 18px 0 0; max-width: 58ch; color: var(--muted); font-size: 1.05rem; line-height: 1.65; }
        .metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 24px; }
        .metric { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); border-radius: 18px; padding: 16px; }
        .metric strong { display: block; font-size: 1.4rem; }
        .metric span { color: var(--muted); font-size: 0.9rem; }
        .form-panel { background: linear-gradient(180deg, rgba(19,32,56,0.95), rgba(10,18,33,0.95)); }
        .form-grid { display: grid; gap: 12px; grid-template-columns: 1fr 1fr; margin-top: 16px; }
        label { display: grid; gap: 8px; font-size: 0.9rem; color: var(--muted); }
        input, textarea {
            width: 100%;
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.08);
            background: rgba(255,255,255,0.05);
            color: var(--text);
            padding: 13px 14px;
            font: inherit;
            outline: none;
        }
        textarea { min-height: 104px; resize: vertical; }
        input:focus, textarea:focus { border-color: rgba(110,231,200,0.55); box-shadow: 0 0 0 4px rgba(110,231,200,0.12); }
        .span-2 { grid-column: span 2; }
        .actions { display: flex; gap: 12px; margin-top: 14px; flex-wrap: wrap; }
        button { border: 0; border-radius: 999px; padding: 12px 18px; font: inherit; font-weight: 700; cursor: pointer; }
        .primary { background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #07111f; }
        .ghost { background: rgba(255,255,255,0.06); color: var(--text); border: 1px solid rgba(255,255,255,0.08); }
        .result { margin-top: 18px; padding: 18px; background: var(--panel-2); border-radius: 18px; border: 1px solid rgba(255,255,255,0.08); min-height: 120px; white-space: pre-wrap; line-height: 1.55; }
        .status { display: inline-flex; align-items: center; gap: 8px; margin-top: 14px; color: var(--muted); font-size: 0.9rem; }
        .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 14px rgba(110,231,200,0.5); }
        @media (max-width: 980px) { .hero { grid-template-columns: 1fr; } }
        @media (max-width: 640px) { .shell { padding: 18px 14px 32px; } .brand, .form-panel { padding: 18px; } .metrics, .form-grid { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
    </style>
</head>
<body>
    <main class="shell">
        <section class="hero">
            <article class="card brand">
                <div class="eyebrow">Ambient Expense Agent</div>
                <h1>Fast expense review with guardrails built in.</h1>
                <p class="lede">
                    Submit a receipt, flag suspicious patterns, and get a policy-aware review path.
                    The server runs locally for development and demo flows.
                </p>
                <div class="metrics">
                    <div class="metric"><strong>PII</strong><span>Redacted before review</span></div>
                    <div class="metric"><strong>Policy</strong><span>Workflow-backed analysis</span></div>
                    <div class="metric"><strong>Audit</strong><span>Event trail output</span></div>
                </div>
            </article>

            <article class="card form-panel">
                <div class="eyebrow">Local console</div>
                <div style="font-size:1.2rem;font-weight:700;">Expense sandbox</div>
                <div class="status"><span class="dot"></span>Ready to analyze</div>
                <div class="form-grid">
                    <label>Amount <input id="amount" value="45.00" /></label>
                    <label>Currency <input id="currency" value="USD" /></label>
                    <label class="span-2">Submitter <input id="submitter" value="alice@example.com" /></label>
                    <label class="span-2">Category <input id="category" value="Meals" /></label>
                    <label class="span-2">Description <textarea id="description">Lunch with client</textarea></label>
                    <label class="span-2">Date <input id="date" value="2026-06-20" /></label>
                </div>
                <div class="actions">
                    <button class="primary" onclick="runAnalysis()">Analyze expense</button>
                    <button class="ghost" onclick="fillSample()">Load sample</button>
                </div>
                <div id="result" class="result">Awaiting submission.</div>
            </article>
        </section>
    </main>

    <script>
        function fillSample() {
            document.getElementById('amount').value = '45.00';
            document.getElementById('currency').value = 'USD';
            document.getElementById('submitter').value = 'alice@example.com';
            document.getElementById('category').value = 'Meals';
            document.getElementById('description').value = 'Lunch with client';
            document.getElementById('date').value = '2026-06-20';
            document.getElementById('result').textContent = 'Sample loaded. Click Analyze expense.';
        }

        async function runAnalysis() {
            const payload = {
                amount: Number(document.getElementById('amount').value),
                currency: document.getElementById('currency').value,
                submitter: document.getElementById('submitter').value,
                category: document.getElementById('category').value,
                description: document.getElementById('description').value,
                date: document.getElementById('date').value,
            };

            const result = document.getElementById('result');
            result.textContent = 'Analyzing expense...';

            try {
                const response = await fetch('/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || 'Analysis failed');
                }
                result.textContent = JSON.stringify(data, null, 2);
            } catch (error) {
                result.textContent = String(error);
            }
        }
    </script>
</body>
</html>
        """


@fastapi_app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "ambient-expense-agent"}


@fastapi_app.post("/run")
async def run_expense(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        session_service = InMemorySessionService()
        session = session_service.create_session_sync(
            user_id=str(payload.get("submitter", "ambient_user")),
            app_name="expense_agent",
        )
        runner = Runner(
            agent=root_agent,
            session_service=session_service,
            app_name="expense_agent",
        )
        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=json.dumps(payload))],
        )

        events = list(
            runner.run(
                new_message=message,
                user_id=str(payload.get("submitter", "ambient_user")),
                session_id=session.id,
            )
        )
        summaries = []
        for event in events:
            content = getattr(event, "content", None)
            if content and getattr(content, "parts", None):
                text_parts = [
                    part.text for part in content.parts if getattr(part, "text", None)
                ]
                if text_parts:
                    summaries.append(" ".join(text_parts))

        return {
            "events": len(events),
            "summary": summaries[-1] if summaries else "No text content returned.",
        }
    except Exception as exc:
        logger.exception("Expense analysis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
