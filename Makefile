.PHONY: install playground run-test

install:
	uv sync

playground:
	uvx google-agents-cli playground

run-test:
	uvx google-agents-cli run '{"amount": 150.0, "submitter": "alice@company.com", "category": "software", "description": "IDE License", "date": "2026-06-06"}'

serve:
	uv run uvicorn expense_agent.fast_api_app:fastapi_app --host 0.0.0.0 --port 8080
