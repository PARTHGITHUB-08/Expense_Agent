# ambient-expense-agent (Capstone Edition)

**Winner: 5-Day AI Agents Intensive Vibe Coding Course With Google (Agents for Business Track)**

This is a robust Multi-Agent System designed to act as an Automated Expense Auditor. It demonstrates key ADK concepts, robust security guardrails, and native MCP tool integration.

## Architecture Highlights

This project successfully implements all the core requirements of the Capstone project:
1. **Multi-Agent System (ADK)**: Uses multiple `LlmAgent` nodes (`categorization_agent` and `review_agent`) wired through a central workflow graph to isolate responsibilities.
2. **MCP Server Integration**: A standalone `policy_mcp_server.py` hosts dynamic corporate expense policies. The `review_agent` accesses this via a synchronous `get_company_policy` tool wrapping standard MCP client protocols.
3. **Agent Skills**: Custom tools `currency_converter` and `receipt_fraud_check` give the review agent superpowers to calculate exchange rates and detect heuristic anomalies.
4. **Security Features**: A dedicated `security_screen` node aggressively filters PII (SSN, CC numbers) and prevents downstream LLM prompt injection attacks. It strictly enforces Pydantic schema validation.

## Project Structure

```
ambient-expense-agent/
├── app/         # Core agent code
│   ├── agent.py               # Main multi-agent workflow
│   ├── agent_runtime_app.py    # Agent Runtime application logic
│   └── app_utils/             # App utilities and helpers
├── policy_mcp_server.py       # Standalone FastMCP Server
├── tests/                     # Unit, integration, and load tests
├── GEMINI.md                  # AI-assisted development guide
└── pyproject.toml             # Project dependencies
```

> 💡 **Tip:** Use [Gemini CLI](https://github.com/google-gemini/gemini-cli) for AI-assisted development - project context is pre-configured in `GEMINI.md`.

## Requirements

Before you begin, ensure you have:
- **uv**: Python package manager (used for all dependency management in this project) - [Install](https://docs.astral.sh/uv/getting-started/installation/) ([add packages](https://docs.astral.sh/uv/concepts/dependencies/) with `uv add <package>`)
- **agents-cli**: Agents CLI - Install with `uv tool install google-agents-cli`
- **Google Cloud SDK**: For GCP services - [Install](https://cloud.google.com/sdk/docs/install)


## Quick Start

Install `agents-cli` and its skills if not already installed:

```bash
uvx google-agents-cli setup
```

Install required packages:

```bash
agents-cli install
```

Test the agent with a local web server:

```bash
agents-cli playground
```

You can also use features from the [ADK](https://adk.dev/) CLI with `uv run adk`.

## Commands

| Command              | Description                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------- |
| `agents-cli install` | Install dependencies using uv                                                         |
| `agents-cli playground` | Launch local development environment                                                  |
| `agents-cli lint`    | Run code quality checks                                                               |
| `agents-cli eval`    | Evaluate agent behavior (generate, grade, analyze, and more — see `agents-cli eval --help`) |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests                                                        |
| `agents-cli deploy`  | Deploy agent to Agent Runtime                                                                |
| `agents-cli publish gemini-enterprise` | Register deployed agent to Gemini Enterprise                    |

## 🛠️ Project Management

| Command | What It Does |
|---------|--------------|
| `agents-cli scaffold enhance` | Add CI/CD pipelines and Terraform infrastructure |
| `agents-cli infra cicd` | One-command setup of entire CI/CD pipeline + infrastructure |
| `agents-cli scaffold upgrade` | Auto-upgrade to latest version while preserving customizations |

---

## Development

Edit your agent logic in `app/agent.py` and test with `agents-cli playground` - it auto-reloads on save.

## Deployment

```bash
gcloud config set project <your-project-id>
agents-cli deploy
```

To add CI/CD and Terraform, run `agents-cli scaffold enhance`.
To set up your production infrastructure, run `agents-cli infra cicd`.

## Observability

Built-in telemetry exports to Cloud Trace, BigQuery, and Cloud Logging.
