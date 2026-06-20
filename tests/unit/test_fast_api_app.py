from types import SimpleNamespace

import pytest

from expense_agent import fast_api_app


class FakeSessionService:
    def __init__(self) -> None:
        self.initial_session = SimpleNamespace(id="session-1", events=[])
        self.updated_session = SimpleNamespace(
            id="session-1",
            events=[
                SimpleNamespace(
                    node_name="record_outcome",
                    output={"status": "approved", "reason": "test outcome"},
                    content=None,
                    actions=None,
                )
            ],
        )

    def create_session_sync(self, user_id: str, app_name: str):
        return self.initial_session

    def get_session_sync(self, app_name: str, user_id: str, session_id: str):
        return self.updated_session


class FakeRunner:
    def __init__(self, **kwargs) -> None:
        pass

    def run(self, **kwargs):
        return iter(())


@pytest.mark.asyncio
async def test_run_expense_extracts_updated_session_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fast_api_app, "session_service", FakeSessionService())
    monkeypatch.setattr(fast_api_app, "Runner", FakeRunner)

    result = await fast_api_app.run_expense(
        {
            "amount": 45.0,
            "submitter": "alice@example.com",
            "category": "Meals",
            "description": "Lunch with client",
            "date": "2026-06-20",
            "currency": "INR",
        }
    )

    assert result["session_id"] == "session-1"
    assert result["outcome"] == {"status": "approved", "reason": "test outcome"}
