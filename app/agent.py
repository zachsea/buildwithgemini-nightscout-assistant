# ruff: noqa
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

import datetime
from zoneinfo import ZoneInfo

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types


MODEL = "gemini-3.6-flash"


from app.nightscout_tools import (
    get_nightscout_profile,
    update_nightscout_profile,
    fetch_current_glucose,
    fetch_glucose_trends,
    fetch_recent_treatments,
)
from google.adk.code_executors import AgentEngineSandboxCodeExecutor

from a2ui.schema.manager import A2uiSchemaManager
from a2ui.basic_catalog.provider import BasicCatalog
from .a2ui_utils import a2ui_callback

schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "A conversational health assistant that helps users understand and manage their diabetes "
        "by analyzing recent glucose readings, insulin deliveries, and treatments from their Nightscout instance."
    ),
    workflow_description=(
        "Analyze the user's request. Use fetch_current_glucose for real-time blood glucose and trend arrows.\n"
        "Use fetch_glucose_trends to inspect historical glucose readings, trends, trajectory, average glucose, min/max, time-in-range percentage, and timeline.\n"
        "Use fetch_recent_treatments to inspect insulin deliveries, boluses, temporary basal changes, and carb intakes.\n"
        "Use get_nightscout_profile to view configuration and target ranges, and update_nightscout_profile to save updates.\n"
        "SECURITY & PRIVACY: NEVER output, display, or reveal the user's API key, token, or secret credentials in any message, card, or text. "
        "If referencing credentials, simply state that the API token is safely configured.\n"
        "Return structured A2UI cards when appropriate to present glucose readings, insulin trends, or summaries."
    ),
    ui_description=(
        "Surface Architecture:\n"
        "- Keep every surface flat: exactly ONE Card > ONE root Column.\n"
        "- Never nest a Card inside a Card.\n"
        "- Use ONLY these components: Card, Column, Row, Text, Divider, and Image.\n"
        "- No markdown inside text. Use usageHint property ('h1', 'h2', 'h3', 'h4', 'caption', 'body') for hierarchy.\n"
        "- For rows with label on the left and value on the right, use Row with distribution='spaceBetween'.\n"
        "\n"
        "Specialized Layout for Glucose Trends & History:\n"
        "When the user asks about glucose trends, history, trajectory, or recent readings, structure the A2UI card cleanly:\n"
        "1. Header Row (Row with distribution='spaceBetween'):\n"
        "   - Left: Text 'h2' -> '🩸 Glucose Trends & Trajectory'\n"
        "   - Right: Text 'caption' -> 'Last 2 Hours CGM' or active time\n"
        "2. Divider\n"
        "3. Metrics Summary Row (Row with distribution='spaceBetween' containing 3 Columns):\n"
        "   - Column 1: Text 'h1' (e.g. '186') + Text 'caption' ('Current mg/dL (→)')\n"
        "   - Column 2: Text 'h1' (e.g. '193') + Text 'caption' ('Average mg/dL')\n"
        "   - Column 3: Text 'h1' (e.g. '75%' or '0%') + Text 'caption' ('Time in Range')\n"
        "4. Divider\n"
        "5. Range Extremes Row (Row with distribution='spaceBetween'):\n"
        "   - Left: Text 'body' -> 'Range: Min 182 – Max 201 mg/dL'\n"
        "   - Right: Text 'caption' -> 'Target: 70–180 mg/dL'\n"
        "6. Divider\n"
        "7. Readings Timeline Section:\n"
        "   - Text 'h3' -> 'Recent Readings'\n"
        "   - For each recent reading (up to 5-6): Row (distribution='spaceBetween') with Left Text 'body' (timestamp e.g. '22:39 UTC') and Right Text 'h4' (reading & arrow, e.g. '186 mg/dL (→ Flat)')\n"
        "8. Divider\n"
        "9. Clinical / Behavioral Insight: Text 'caption' -> summary insight (e.g. '💡 Glucose has leveled off at ~186 mg/dL, slightly above your 180 mg/dL target threshold.').\n"
        "\n"
        "Specialized Layout for Insulin & Treatments:\n"
        "When the user asks about treatments, insulin doses, boluses, or basals, structure the A2UI card cleanly:\n"
        "1. Header Row (Row with distribution='spaceBetween'):\n"
        "   - Left: Text 'h2' -> '💉 Recent Treatments & Insulin'\n"
        "   - Right: Text 'caption' -> time or 'Active Pump Log'\n"
        "2. Divider\n"
        "3. Metrics Summary Row (Row with distribution='spaceBetween' containing 2-3 Columns):\n"
        "   - Column 1: Text 'h1' (e.g. '10.2 U') + Text 'caption' ('Total Bolused')\n"
        "   - Column 2: Text 'h1' (e.g. '0.40') + Text 'caption' ('Basal Rate U/h')\n"
        "   - Column 3: Text 'h1' (e.g. '130g') + Text 'caption' ('Carbs Logged')\n"
        "4. Divider\n"
        "5. Bolus History Section:\n"
        "   - Text 'h3' -> 'Bolus Deliveries'\n"
        "   - For each recent bolus (up to 4): Row (distribution='spaceBetween') with Left Text 'body' (timestamp & event type) and Right Text 'h4' (units dosage, e.g. '1.90 U')\n"
        "6. If carbs exist, an 'h3' 'Carb Intake' with Row (distribution='spaceBetween') items.\n"
        "7. Divider\n"
        "8. Clinical Safety Advisory: Text 'caption' -> '⚠️ Verify active Insulin on Board (IOB) on your pump or Nightscout before delivering correction doses.'\n"
        "\n"
        "Output ONLY the raw A2UI JSON array — no markdown fences, no explanatory prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=a2ui_instruction,
    tools=[
        get_nightscout_profile,
        update_nightscout_profile,
        fetch_current_glucose,
        fetch_glucose_trends,
        fetch_recent_treatments,
    ],
    code_executor=AgentEngineSandboxCodeExecutor(),
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
