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

# Declare a global SessionService to persist sessions across requests
session_service = InMemorySessionService()

fastapi_app = FastAPI(title="Ambient Expense Agent", version="0.1.0")


def find_tool_response(events: list[Any], call_id: str) -> str | None:
    """Traverse session events to find the response payload for a function call ID."""
    for event in events:
        content = getattr(event, "content", None)
        if content and getattr(content, "parts", None):
            for part in content.parts:
                if (
                    getattr(part, "function_response", None)
                    and part.function_response.id == call_id
                ):
                    result = part.function_response.response
                    if isinstance(result, dict) and "result" in result:
                        return result["result"]
                    return str(result)
    return None


def extract_audit_data(session: Any) -> dict[str, Any]:
    """Inspect session events to build a structured audit trace of agent execution."""
    audit = {
        "redacted": False,
        "redacted_categories": [],
        "categorization": None,
        "policy": None,
        "fraud_check": None,
        "currency_conversion": None,
        "review": None,
        "outcome": None,
        "pending_approval": False,
        "approval_message": None,
        "interrupt_id": None,
        "session_id": session.id,
    }

    for event in session.events:
        # Check categorization agent output
        if event.node_name == "categorization_agent":
            if event.output:
                if isinstance(event.output, dict):
                    audit["categorization"] = event.output
                else:
                    audit["categorization"] = getattr(
                        event.output, "model_dump", lambda: {}
                    )()

        # Check review agent output
        if event.node_name == "review_agent":
            if event.output:
                if isinstance(event.output, dict):
                    audit["review"] = event.output
                else:
                    audit["review"] = getattr(event.output, "model_dump", lambda: {})()

        # Check tool calls
        content = getattr(event, "content", None)
        if content and getattr(content, "parts", None):
            for part in content.parts:
                if getattr(part, "function_call", None):
                    fc = part.function_call
                    if fc.name == "get_company_policy":
                        audit["policy"] = find_tool_response(session.events, fc.id)
                    elif fc.name == "receipt_fraud_check":
                        audit["fraud_check"] = find_tool_response(session.events, fc.id)
                    elif fc.name == "currency_converter":
                        audit["currency_conversion"] = {
                            "amount": fc.args.get("amount"),
                            "currency": fc.args.get("currency"),
                            "converted": find_tool_response(session.events, fc.id),
                        }

        # Check final outcome
        if event.node_name == "record_outcome":
            if event.output:
                audit["outcome"] = event.output

    # Check if currently pending human approval
    if session.events:
        last_event = session.events[-1]
        last_content = getattr(last_event, "content", None)
        if last_content and getattr(last_content, "parts", None):
            for part in last_content.parts:
                if (
                    getattr(part, "function_call", None)
                    and part.function_call.name == "adk_request_input"
                ):
                    audit["pending_approval"] = True
                    audit["approval_message"] = part.function_call.args.get("message")
                    audit["interrupt_id"] = part.function_call.id

    # Check state delta changes for PII redactions
    for event in session.events:
        actions = getattr(event, "actions", None)
        if actions and getattr(actions, "state_delta", None):
            delta = actions.state_delta
            if "redacted_categories" in delta:
                audit["redacted"] = True
                audit["redacted_categories"] = delta["redacted_categories"]

    return audit


@fastapi_app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ambient Expense Auditor</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@500;600;700&display=swap" rel="stylesheet" />
    <style>
        :root {
            --bg: #080f1e;
            --panel: rgba(13, 22, 43, 0.75);
            --panel-border: rgba(255, 255, 255, 0.07);
            --text: #f1f5f9;
            --muted: #94a3b8;
            --accent: #06d6a0;
            --accent-glow: rgba(6, 214, 160, 0.25);
            --accent-blue: #3b82f6;
            --accent-orange: #ff9f43;
            --accent-red: #ef476f;
            --radius: 24px;
            --shadow: 0 35px 80px rgba(0, 0, 0, 0.45);
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
            color: var(--text);
            background:
                radial-gradient(circle at 10% 10%, rgba(6, 214, 160, 0.12), transparent 40%),
                radial-gradient(circle at 90% 10%, rgba(59, 130, 246, 0.15), transparent 40%),
                linear-gradient(155deg, #050a14 0%, #0d1629 60%, #080f1e 100%);
            display: flex;
            align-items: center;
        }
        .shell { width: 100%; max-width: 1200px; margin: 0 auto; padding: 40px 24px; }
        .hero { display: grid; gap: 30px; grid-template-columns: 1fr 1.1fr; align-items: stretch; }
        .card {
            background: var(--panel);
            border: 1px solid var(--panel-border);
            box-shadow: var(--shadow);
            border-radius: var(--radius);
            backdrop-filter: blur(20px);
            padding: 36px;
        }
        .eyebrow {
            text-transform: uppercase;
            letter-spacing: 0.24em;
            color: var(--accent);
            font-size: 0.76rem;
            font-weight: 700;
            margin-bottom: 12px;
            font-family: 'Outfit', sans-serif;
        }
        h1 { margin: 0 0 20px; font-family: 'Outfit', sans-serif; font-size: 1.8rem; font-weight: 700; }
        .form-grid { display: grid; gap: 16px; grid-template-columns: 1fr 1fr; }
        label { display: grid; gap: 8px; font-size: 0.88rem; color: var(--muted); font-weight: 500; }
        input, textarea {
            width: 100%;
            border-radius: 14px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            background: rgba(255, 255, 255, 0.04);
            color: var(--text);
            padding: 13px 16px;
            font: inherit;
            outline: none;
            transition: all 0.25s ease;
        }
        textarea { min-height: 108px; resize: vertical; }
        input:focus, textarea:focus {
            border-color: rgba(6, 214, 160, 0.5);
            background: rgba(255, 255, 255, 0.07);
            box-shadow: 0 0 0 4px var(--accent-glow);
        }
        .span-2 { grid-column: span 2; }
        .actions { display: flex; gap: 14px; margin-top: 24px; }
        button {
            border: 0;
            border-radius: 999px;
            padding: 14px 24px;
            font: inherit;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .primary {
            background: linear-gradient(135deg, var(--accent), #1dd1a1);
            color: #050b15;
            box-shadow: 0 4px 15px var(--accent-glow);
        }
        .primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px var(--accent-glow);
        }
        .ghost {
            background: rgba(255, 255, 255, 0.05);
            color: var(--text);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .ghost:hover {
            background: rgba(255, 255, 255, 0.09);
        }

        /* Loading Overlay */
        .hidden { display: none !important; }
        .spinner {
            width: 40px;
            height: 40px;
            border: 3.5px solid rgba(255, 255, 255, 0.1);
            border-radius: 50%;
            border-top-color: var(--accent);
            animation: spin 0.9s linear infinite;
            margin: 40px auto 20px;
        }

        /* Timeline Audit steps */
        .timeline { display: flex; flex-direction: column; gap: 20px; margin-top: 10px; }
        .step { display: flex; gap: 16px; position: relative; animation: fadeIn 0.4s ease forwards; }
        .step::before {
            content: '';
            position: absolute;
            left: 17px;
            top: 36px;
            bottom: -22px;
            width: 2px;
            background: rgba(255, 255, 255, 0.06);
        }
        .step:last-child::before { display: none; }
        .step-icon {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.1rem;
            z-index: 1;
            flex-shrink: 0;
            box-shadow: 0 4px 10px rgba(0,0,0,0.25);
        }
        .step-content {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 18px;
            padding: 16px 20px;
            width: 100%;
        }
        .step-title { font-weight: 700; font-size: 0.98rem; margin-bottom: 6px; }
        .step-desc { color: var(--muted); font-size: 0.9rem; line-height: 1.5; }

        .success-bg { background: rgba(6, 214, 160, 0.1); border: 1px solid rgba(6, 214, 160, 0.2); color: var(--accent); }
        .danger-bg { background: rgba(239, 71, 111, 0.1); border: 1px solid rgba(239, 71, 111, 0.2); color: var(--accent-red); }
        .info-bg { background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.2); color: var(--accent-blue); }
        .warning-bg { background: rgba(255, 159, 67, 0.1); border: 1px solid rgba(255, 159, 67, 0.2); color: var(--accent-orange); }

        /* Interactive Decisions and Outcome Banner */
        .decision-panel {
            background: linear-gradient(135deg, rgba(255, 159, 67, 0.12) 0%, rgba(239, 71, 111, 0.12) 100%);
            border: 1px solid rgba(255, 159, 67, 0.35);
            border-radius: 20px;
            padding: 22px;
            margin-top: 20px;
            animation: pulseBorder 2s infinite alternate;
        }
        .decision-actions { display: flex; gap: 12px; margin-top: 16px; }
        .btn-approve { background: var(--accent); color: #050b15; }
        .btn-approve:hover { box-shadow: 0 4px 15px rgba(6, 214, 160, 0.4); transform: translateY(-1px); }
        .btn-reject { background: var(--accent-red); color: var(--text); }
        .btn-reject:hover { box-shadow: 0 4px 15px rgba(239, 71, 111, 0.4); transform: translateY(-1px); }

        .outcome-banner {
            border-radius: 20px;
            padding: 22px;
            margin-top: 20px;
            font-weight: 700;
            display: flex;
            flex-direction: column;
            gap: 8px;
            animation: fadeIn 0.4s ease forwards;
        }
        .outcome-approved {
            background: rgba(6, 214, 160, 0.15);
            border: 1px solid rgba(6, 214, 160, 0.35);
            color: var(--accent);
        }
        .outcome-rejected {
            background: rgba(239, 71, 111, 0.15);
            border: 1px solid rgba(239, 71, 111, 0.35);
            color: var(--accent-red);
        }

        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(12px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulseBorder {
            from { border-color: rgba(255, 159, 67, 0.35); box-shadow: 0 0 10px rgba(255, 159, 67, 0.05); }
            to { border-color: rgba(255, 159, 67, 0.65); box-shadow: 0 0 20px rgba(255, 159, 67, 0.2); }
        }

        @media (max-width: 1024px) { .hero { grid-template-columns: 1fr; } }
        @media (max-width: 640px) {
            .shell { padding: 24px 16px; }
            .card { padding: 24px; }
            .form-grid { grid-template-columns: 1fr; }
            .span-2 { grid-column: span 1; }
            .decision-actions { flex-direction: column; }
        }
    </style>
</head>
<body>
    <main class="shell">
        <section class="hero">
            <!-- Left Card: Input form -->
            <article class="card form-panel">
                <div class="eyebrow">Interactive Console</div>
                <h1>Expense Sandbox</h1>
                <p style="color: var(--muted); font-size: 0.9rem; margin-top: -10px; margin-bottom: 24px; line-height: 1.5;">
                    Verify policies, heuristic fraud markers, and PII shields in real time. Default currency is locked to INR.
                </p>
                <div class="form-grid">
                    <label>Amount <input id="amount" value="45.00" type="number" step="0.01" /></label>
                    <label>Currency <input id="currency" value="INR" readonly style="opacity: 0.65; cursor: not-allowed; font-weight: 600;" /></label>
                    <label class="span-2">Submitter <input id="submitter" value="alice@company.com" /></label>
                    <label class="span-2">Category <input id="category" value="Meals" /></label>
                    <label class="span-2">Description <textarea id="description">Client lunch to finalize the project contract details.</textarea></label>
                    <label class="span-2">Date <input id="date" value="2026-06-20" type="date" /></label>
                </div>
                <div class="actions">
                    <button class="primary" onclick="runAnalysis()">Analyze Expense</button>
                    <button class="ghost" onclick="fillSample()">Load HITL Sample</button>
                </div>
            </article>

            <!-- Right Card: Audit Steps output -->
            <article class="card brand" style="display: flex; flex-direction: column;">
                <div class="eyebrow">Audit Path</div>
                <h1 style="margin-bottom: 24px;">Workflow Audit Timeline</h1>

                <div id="loading" class="hidden" style="text-align: center; margin: auto;">
                    <div class="spinner"></div>
                    <p style="color: var(--muted); font-weight: 500; font-size: 0.95rem;">Executing agent workflow...</p>
                </div>

                <div id="waiting-panel" style="text-align: center; margin: auto; padding: 40px 10px;">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="color: var(--muted); margin-bottom: 20px; opacity: 0.8;">
                        <circle cx="12" cy="12" r="10"/>
                        <path d="M12 8v4l3 3"/>
                    </svg>
                    <div style="font-size: 1.1rem; font-weight: 700; margin-bottom: 8px; font-family: 'Outfit', sans-serif;">Awaiting Submission</div>
                    <p style="color: var(--muted); margin: 0; font-size: 0.92rem; max-width: 32ch; line-height: 1.5; margin-left: auto; margin-right: auto;">
                        Click Analyze Expense to see the step-by-step multi-agent review details.
                    </p>
                </div>

                <div id="audit-results" class="hidden" style="flex: 1; display: flex; flex-direction: column;">
                    <div class="timeline" id="timeline"></div>
                    <div id="decision-area"></div>
                </div>
            </article>
        </section>
    </main>

    <script>
        let currentSessionId = null;
        let currentInterruptId = null;
        let currentSubmitter = null;

        function fillSample() {
            document.getElementById('amount').value = '150.00';
            document.getElementById('currency').value = 'INR';
            document.getElementById('submitter').value = 'alice@company.com';
            document.getElementById('category').value = 'Software';
            document.getElementById('description').value = 'IDE license subscription. SSN: 000-12-3456';
            document.getElementById('date').value = '2026-06-20';
        }

        function showLoading(show) {
            if (show) {
                document.getElementById('loading').classList.remove('hidden');
                document.getElementById('waiting-panel').classList.add('hidden');
                document.getElementById('audit-results').classList.add('hidden');
            } else {
                document.getElementById('loading').classList.add('hidden');
            }
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
            currentSubmitter = payload.submitter;
            showLoading(true);
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
                renderAudit(data);
            } catch (error) {
                renderError(error.message);
            } finally {
                showLoading(false);
            }
        }

        async function submitDecision(decision) {
            if (!currentSessionId || !currentInterruptId) return;
            const payload = {
                session_id: currentSessionId,
                submitter: currentSubmitter,
                decision: decision,
                interrupt_id: currentInterruptId
            };
            showLoading(true);
            try {
                const response = await fetch('/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || 'Decision submission failed');
                }
                renderAudit(data);
            } catch (error) {
                renderError(error.message);
            } finally {
                showLoading(false);
            }
        }

        function renderAudit(data) {
            document.getElementById('waiting-panel').classList.add('hidden');
            document.getElementById('audit-results').classList.remove('hidden');

            const timeline = document.getElementById('timeline');
            timeline.innerHTML = '';

            const decisionArea = document.getElementById('decision-area');
            decisionArea.innerHTML = '';

            currentSessionId = data.session_id;
            currentInterruptId = data.interrupt_id;

            // Step 1: Security Redaction
            let securityHtml = '';
            if (data.redacted) {
                securityHtml = `
                    <div class="step">
                        <div class="step-icon warning-bg">🛡️</div>
                        <div class="step-content">
                            <div class="step-title" style="color: var(--accent-orange);">Security Shield: Redacted</div>
                            <div class="step-desc">
                                PII detected and redacted in description. Redacted types:
                                <strong style="color: var(--accent-orange);">${data.redacted_categories.join(', ')}</strong>.
                            </div>
                        </div>
                    </div>
                `;
            } else {
                securityHtml = `
                    <div class="step">
                        <div class="step-icon success-bg">🛡️</div>
                        <div class="step-content">
                            <div class="step-title" style="color: var(--accent);">Security Shield: Clean</div>
                            <div class="step-desc">Checked for PII (SSN, credit card) and prompt injection. No threats detected.</div>
                        </div>
                    </div>
                `;
            }
            timeline.innerHTML += securityHtml;

            // Step 2: Categorization
            if (data.categorization) {
                const cat = data.categorization;
                const catHtml = `
                    <div class="step">
                        <div class="step-icon info-bg">🏷️</div>
                        <div class="step-content">
                            <div class="step-title" style="color: var(--accent-blue);">Categorization Agent</div>
                            <div class="step-desc">
                                Assigned category: <strong style="color: var(--accent-blue);">${cat.corporate_category}</strong>.<br/>
                                Currency conversion: <strong>${cat.requires_conversion ? 'Required (INR → USD)' : 'Not needed'}</strong>.<br/>
                                <span style="display: block; margin-top: 6px; opacity: 0.95; font-style: italic;">Notes: ${cat.notes}</span>
                            </div>
                        </div>
                    </div>
                `;
                timeline.innerHTML += catHtml;
            }

            // Step 3: Policy Check
            if (data.policy) {
                const policyHtml = `
                    <div class="step">
                        <div class="step-icon warning-bg">📋</div>
                        <div class="step-content">
                            <div class="step-title" style="color: var(--accent-orange);">MCP Policy Server</div>
                            <div class="step-desc">${data.policy}</div>
                        </div>
                    </div>
                `;
                timeline.innerHTML += policyHtml;
            }

            // Step 4: Fraud Audit
            if (data.fraud_check) {
                const fraudHtml = `
                    <div class="step">
                        <div class="step-icon info-bg">🔍</div>
                        <div class="step-content">
                            <div class="step-title" style="color: var(--accent-blue);">Fraud Heuristics</div>
                            <div class="step-desc">${data.fraud_check}</div>
                        </div>
                    </div>
                `;
                timeline.innerHTML += fraudHtml;
            }

            // Step 5: Review Summary
            if (data.review) {
                const review = data.review;
                const riskColor = review.alert_raised ? 'var(--accent-red)' : 'var(--accent)';
                const icon = review.alert_raised ? '🚨' : '✅';
                const bgClass = review.alert_raised ? 'danger-bg' : 'success-bg';

                let risksHtml = '';
                if (review.risk_factors && review.risk_factors.length > 0) {
                    risksHtml = `
                        <ul style="margin: 8px 0 0 0; padding-left: 20px; font-size: 0.88rem; color: var(--accent-red);">
                            ${review.risk_factors.map(r => `<li>${r}</li>`).join('')}
                        </ul>
                    `;
                }

                const reviewHtml = `
                    <div class="step">
                        <div class="step-icon ${bgClass}">${icon}</div>
                        <div class="step-content">
                            <div class="step-title" style="color: ${riskColor};">Risk Analyst Review</div>
                            <div class="step-desc">
                                <strong>Summary:</strong> ${review.summary}
                                ${risksHtml}
                            </div>
                        </div>
                    </div>
                `;
                timeline.innerHTML += reviewHtml;
            }

            // Step 6: Outcome / Decisions
            if (data.pending_approval) {
                decisionArea.innerHTML = `
                    <div class="decision-panel">
                        <div style="font-weight: 700; color: var(--accent-orange); display: flex; align-items: center; gap: 8px;">
                            <span>⚠️</span> Human approval required
                        </div>
                        <p style="margin: 8px 0 0 0; font-size: 0.9rem; line-height: 1.5; color: var(--text);">
                            ${data.approval_message}
                        </p>
                        <div class="decision-actions">
                            <button class="primary btn-approve" onclick="submitDecision('Approve')">Approve Expense</button>
                            <button class="primary btn-reject" onclick="submitDecision('Reject')">Reject Expense</button>
                        </div>
                    </div>
                `;
            } else if (data.outcome) {
                const out = data.outcome;
                const isApproved = out.status === 'approved' || out.status === 'Approve';
                const bannerClass = isApproved ? 'outcome-approved' : 'outcome-rejected';
                const bannerTitle = isApproved ? 'Expense Approved' : 'Expense Rejected';
                const bannerIcon = isApproved ? '🎉' : '❌';

                decisionArea.innerHTML = `
                    <div class="outcome-banner ${bannerClass}">
                        <div style="font-size: 1.1rem; display: flex; align-items: center; gap: 8px;">
                            <span>${bannerIcon}</span> ${bannerTitle}
                        </div>
                        <div style="font-size: 0.9rem; font-weight: normal; opacity: 0.9;">
                            Reason: ${out.reason}
                        </div>
                    </div>
                `;
            }
        }

        function renderError(message) {
            document.getElementById('waiting-panel').classList.add('hidden');
            document.getElementById('audit-results').classList.remove('hidden');
            document.getElementById('timeline').innerHTML = '';
            document.getElementById('decision-area').innerHTML = `
                <div class="outcome-banner outcome-rejected">
                    <div style="font-size: 1.1rem; display: flex; align-items: center; gap: 8px;">
                        <span>❌</span> Error
                    </div>
                    <div style="font-size: 0.9rem; font-weight: normal;">
                        ${message}
                    </div>
                </div>
            `;
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
        session_id = payload.get("session_id")
        user_id = str(payload.get("submitter", "ambient_user"))

        if session_id:
            session = session_service.get_session_sync(
                app_name="expense_agent",
                user_id=user_id,
                session_id=session_id,
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
        else:
            session = session_service.create_session_sync(
                user_id=user_id,
                app_name="expense_agent",
            )

        runner = Runner(
            agent=root_agent,
            session_service=session_service,
            app_name="expense_agent",
        )

        if "decision" in payload:
            decision = payload["decision"]
            interrupt_id = payload.get("interrupt_id", "human_approval")
            response_part = types.Part(
                function_response=types.FunctionResponse(
                    id=interrupt_id,
                    name="adk_request_input",
                    response={interrupt_id: decision},
                )
            )
            message = types.Content(role="user", parts=[response_part])
        else:
            message = types.Content(
                role="user",
                parts=[types.Part.from_text(text=json.dumps(payload))],
            )

        # Execute the workflow
        _ = list(
            runner.run(
                new_message=message,
                user_id=user_id,
                session_id=session.id,
            )
        )

        # Extract audit details and return
        audit_data = extract_audit_data(session)
        return audit_data
    except Exception as exc:
        logger.exception("Expense analysis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
