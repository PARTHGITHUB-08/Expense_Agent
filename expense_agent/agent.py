import asyncio
import base64
import json
import re
import threading
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events import RequestInput
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.workflow import START, Edge, Workflow, node
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, ValidationError

from .config import EXPENSE_THRESHOLD_USD, REVIEW_MODEL


class Expense(BaseModel):
    amount: float
    submitter: str
    category: str
    description: str
    date: str
    currency: str = "USD"


class ReviewOutput(BaseModel):
    risk_factors: list[str]
    alert_raised: bool
    summary: str


class CategorizationOutput(BaseModel):
    corporate_category: str
    requires_conversion: bool
    notes: str


def _normalize_expense_payload(
    node_input: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        if isinstance(node_input, types.Content):
            payload = node_input.parts[0].text.strip()
            data = json.loads(payload) if payload else {}
        else:
            if isinstance(node_input, dict):
                data = node_input
            else:
                stripped = str(node_input).strip()
                data = json.loads(stripped) if stripped else {}
    except json.JSONDecodeError:
        data = {}

    if "data" in data and isinstance(data["data"], str):
        try:
            decoded = base64.b64decode(data["data"]).decode("utf-8")
            expense_data = json.loads(decoded)
        except Exception:
            expense_data = (
                json.loads(data["data"])
                if isinstance(data["data"], str)
                else data["data"]
            )
    else:
        expense_data = data

    if not isinstance(expense_data, dict):
        return None, (
            "Please send an expense as JSON with amount, submitter, category, "
            "description, date, and optional currency."
        )

    try:
        Expense(**expense_data)
    except ValidationError:
        return None, (
            "I couldn't parse that as a complete expense. Please resend JSON with "
            "amount, submitter, category, description, date, and optional currency."
        )

    return expense_data, None


# --- SKILLS (TOOLS) ---


def currency_converter(amount: float, currency: str) -> float:
    """Converts a foreign currency amount to USD."""
    rates = {
        "EUR": 1.1,
        "GBP": 1.25,
        "JPY": 0.0065,
        "CAD": 0.74,
        "AUD": 0.65,
        "INR": 0.012,
    }
    currency = currency.upper()
    if currency == "USD":
        return amount
    return amount * rates.get(currency, 1.0)


def get_company_policy(category: str) -> str:
    """Fetches the company policy for a given expense category using the Policy MCP Server."""

    async def fetch():
        server_params = StdioServerParameters(
            command="python", args=["policy_mcp_server.py"], env=None
        )
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "get_expense_policy", arguments={"category": category}
                    )
                    return result.content[0].text
        except Exception as e:
            return f"Error fetching policy: {e!s}"

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            result_container = []

            def run_in_thread():
                result_container.append(asyncio.run(fetch()))

            t = threading.Thread(target=run_in_thread)
            t.start()
            t.join()
            return result_container[0]
        else:
            return asyncio.run(fetch())
    except RuntimeError:
        return asyncio.run(fetch())


def receipt_fraud_check(merchant_name: str, amount: float) -> str:
    """Advanced heuristic check to detect potential fraud based on merchant name and amount patterns."""
    suspicious_merchants = ["cash", "venmo", "paypal", "crypto", "atm"]
    merchant_lower = merchant_name.lower()
    if any(sm in merchant_lower for sm in suspicious_merchants):
        return f"HIGH RISK: Merchant '{merchant_name}' is on the restricted payment methods list."

    # Check for round number amounts (often flagged in manual entries)
    if amount % 100 == 0 and amount > 500:
        return f"MEDIUM RISK: Large, perfectly round amount (${amount}). Verify receipt accuracy."

    return "Fraud check passed: No immediate suspicious patterns detected."


# --- NODES ---


@node
def parse_expense(node_input: Any) -> Event:
    """Parses incoming JSON/pubsub payload into an Expense model. Strictly validates."""
    expense_data, clarification = _normalize_expense_payload(node_input)
    if expense_data is None:
        return Event(
            output={"status": "needs_input", "message": clarification},
            actions=EventActions(route="record_outcome"),
            state={"status": "needs_input"},
        )

    expense = Expense(**expense_data)

    state_updates = {"expense": expense.model_dump()}

    return Event(
        output=expense.model_dump_json(), route="categorize", state=state_updates
    )


categorization_agent = LlmAgent(
    name="categorization_agent",
    model=REVIEW_MODEL,
    instruction="You are an expert expense categorizer. Review the raw expense, assign a standard corporate category (like 'Travel', 'Meals', 'Software', 'Hardware'), and note if it requires currency conversion.",
    output_schema=CategorizationOutput,
    output_key="categorization_result",
)


@node
def security_screen(ctx: Context, node_input: CategorizationOutput) -> Event:
    """Security checkpoint for PII and prompt injection."""
    expense_data = ctx.state.get("expense", {})
    desc = expense_data.get("description", "")
    redacted_categories = []

    if re.search(r"\b\d{3}-\d{2}-\d{4}\b", desc):
        desc = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED SSN]", desc)
        redacted_categories.append("SSN")

    if re.search(r"\b(?:\d{4}-){3}\d{4}\b|\b\d{16}\b", desc):
        desc = re.sub(r"\b(?:\d{4}-){3}\d{4}\b|\b\d{16}\b", "[REDACTED CC]", desc)
        redacted_categories.append("Credit Card")

    lower_desc = desc.lower()
    injection_keywords = ["ignore previous", "auto-approve", "bypass", "force approve"]
    is_injection = any(kw in lower_desc for kw in injection_keywords)

    expense_data["description"] = desc

    state_updates = {"expense": expense_data, "category": node_input.model_dump()}
    if redacted_categories:
        state_updates["redacted_categories"] = redacted_categories

    if is_injection:
        alert = ReviewOutput(
            risk_factors=["SECURITY EVENT: Potential Prompt Injection Detected!"],
            alert_raised=True,
            summary="This expense report contains instructions attempting to bypass the agent's rules.",
        )
        return Event(output=alert, route="injection_detected", state=state_updates)
    else:
        prompt = f"Categorization: {node_input.model_dump_json()}\nExpense: {json.dumps(expense_data)}\nPlease review this expense against company policies. Convert currencies if necessary, and fetch the latest policy limits."
        return Event(output=prompt, route="clean", state=state_updates)


@node
def auto_approve(ctx: Context, node_input: ReviewOutput) -> Event:
    """Automatically approves if no risks and under threshold."""
    result = {
        "status": "approved",
        "reason": "auto-approved: no risks found by review agent",
        "details": node_input.model_dump(),
    }
    return Event(output=result, state={"status": "approved"})


# LLM Node to review risks
review_agent = LlmAgent(
    name="review_agent",
    model=REVIEW_MODEL,
    instruction="You are a corporate expense risk analyst. Use the tools provided to fetch policy limits, check for fraud, and convert currencies if necessary. Then identify any policy violations or risk factors. If there are risks, set alert_raised to true.",
    tools=[currency_converter, get_company_policy, receipt_fraud_check],
    output_schema=ReviewOutput,
    output_key="review_result",
)


@node(rerun_on_resume=False)
async def human_review(ctx: Context, node_input: ReviewOutput):
    """Pauses for human-in-the-loop review on high-risk expenses."""
    expense_data = ctx.state.get("expense", {})

    if not ctx.resume_inputs:
        msg = f"High risk expense from {expense_data.get('submitter')} for {expense_data.get('currency')} {expense_data.get('amount')}. Risk factors: {node_input.risk_factors}. Approve or Reject?"
        yield RequestInput(interrupt_id="human_approval", message=msg)
        return

    decision = ctx.resume_inputs.get("human_approval")
    result = {"status": decision, "reason": f"human decision: {decision}"}
    yield Event(output=result, state={"status": decision})


@node
def evaluate_review(ctx: Context, node_input: ReviewOutput) -> Event:
    """Evaluate review agent output to route to auto_approve or human_review."""
    expense_data = ctx.state.get("expense", {})
    amount = expense_data.get("amount", 0)

    if node_input.alert_raised or amount > EXPENSE_THRESHOLD_USD:
        return Event(output=node_input, route="human_review")
    return Event(output=node_input, route="auto_approve")


@node
def record_outcome(node_input: Any) -> Any:
    """Final node to log the outcome."""
    print(f"Outcome recorded: {node_input}")
    if isinstance(node_input, dict) and "message" in node_input:
        content_text = str(node_input["message"])
    elif isinstance(node_input, (dict, list)):
        content_text = json.dumps(node_input, indent=2, ensure_ascii=False)
    else:
        content_text = str(node_input)

    return Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=content_text)],
        ),
        output=node_input,
        state={"final_output": node_input},
    )


# Define the Workflow Graph
root_agent = Workflow(
    name="ambient_expense_agent",
    edges=[
        Edge(from_node=START, to_node=parse_expense),
        Edge(from_node=parse_expense, to_node=record_outcome, route="record_outcome"),
        Edge(from_node=parse_expense, to_node=categorization_agent, route="categorize"),
        Edge(from_node=categorization_agent, to_node=security_screen),
        Edge(from_node=security_screen, to_node=review_agent, route="clean"),
        Edge(
            from_node=security_screen, to_node=human_review, route="injection_detected"
        ),
        Edge(from_node=review_agent, to_node=evaluate_review),
        Edge(from_node=evaluate_review, to_node=human_review, route="human_review"),
        Edge(from_node=evaluate_review, to_node=auto_approve, route="auto_approve"),
        Edge(from_node=auto_approve, to_node=record_outcome),
        Edge(from_node=human_review, to_node=record_outcome),
    ],
)

app = App(
    root_agent=root_agent,
    name="expense_agent",
)
