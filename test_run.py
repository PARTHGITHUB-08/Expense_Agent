from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from expense_agent.agent import root_agent


def run_tests() -> None:
    print("--- Running Test 1: Normal Expense ---")
    expense1 = {
        "amount": 45.0,
        "submitter": "alice@example.com",
        "category": "Meals",
        "description": "Lunch with client",
        "date": "2026-06-20",
        "currency": "USD",
    }

    session_service = InMemorySessionService()
    session = session_service.create_session_sync(user_id="test_user", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=str(expense1).replace("'", '"'))],
    )

    events = list(
        runner.run(
            new_message=message,
            user_id="test_user",
            session_id=session.id,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        )
    )
    print(f"Received {len(events)} events")


if __name__ == "__main__":
    run_tests()
