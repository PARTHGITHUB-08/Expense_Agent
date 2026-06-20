# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging
import os
from typing import Any

import vertexai
from dotenv import load_dotenv
from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
from google.cloud import logging as google_cloud_logging
from vertexai.agent_engines.templates.adk import AdkApp

from expense_agent.agent import app as adk_app
from expense_agent.app_utils.telemetry import setup_telemetry
from expense_agent.app_utils.typing import Feedback

# Load environment variables from .env file at runtime
load_dotenv()


class AgentEngineApp(AdkApp):
    def set_up(self) -> None:
        """Initialize the agent engine app with logging and telemetry."""
        vertexai.init()
        setup_telemetry()
        super().set_up()
        logging.basicConfig(level=logging.INFO)
        logging_client = google_cloud_logging.Client()
        self.logger = logging_client.logger(__name__)
        if gemini_location:
            os.environ["GOOGLE_CLOUD_LOCATION"] = gemini_location

    def register_feedback(self, feedback: dict[str, Any]) -> None:
        """Collect and log feedback."""
        feedback_obj = Feedback.model_validate(feedback)
        self.logger.log_struct(feedback_obj.model_dump(), severity="INFO")

    def register_operations(self) -> dict[str, list[str]]:
        """Registers the operations of the Agent."""
        operations = super().register_operations()
        operations[""] = [*operations.get("", []), "register_feedback"]
        return operations

    def clone(self) -> "AgentEngineApp":
        """Returns a clone of the Agent Runtime application."""
        return self


class LocalAgentRuntimeApp:
    """Fallback runtime used when Google Cloud credentials are unavailable."""

    def __init__(self, app: object) -> None:
        self.app = app
        self.logger = logging.getLogger(__name__)

    def set_up(self) -> None:
        setup_telemetry(app=self.app, otel_to_cloud=False)
        logging.basicConfig(level=logging.INFO)

    def register_feedback(self, feedback: dict[str, Any]) -> None:
        feedback_obj = Feedback.model_validate(feedback)
        self.logger.info("Local feedback received: %s", feedback_obj.model_dump())

    def register_operations(self) -> dict[str, list[str]]:
        return {"": ["register_feedback"]}

    async def async_stream_query(self, message: str, user_id: str):
        from google.genai import types

        yield {
            "content": types.Content(
                role="model",
                parts=[types.Part.from_text(text=f"Local runtime response: {message}")],
            )
        }

    def clone(self) -> "LocalAgentRuntimeApp":
        return self


gemini_location = os.environ.get("GOOGLE_CLOUD_LOCATION")
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")


def build_agent_runtime() -> AgentEngineApp | LocalAgentRuntimeApp:
    try:
        return AgentEngineApp(
            app=adk_app,
            artifact_service_builder=lambda: (
                GcsArtifactService(bucket_name=logs_bucket_name)
                if logs_bucket_name
                else InMemoryArtifactService()
            ),
        )
    except Exception as exc:
        logging.warning("Falling back to local runtime: %s", exc)
        return LocalAgentRuntimeApp(app=adk_app)


agent_runtime = build_agent_runtime()
