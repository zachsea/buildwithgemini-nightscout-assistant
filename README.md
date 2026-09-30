# Nightscout Assistant

A conversational health assistant built with the **Google Agent Development Kit (ADK)** and deployed to **Vertex AI Agent Runtime**, connecting to [Nightscout](https://nightscout.github.io/) to help individuals with diabetes monitor their continuous glucose data, analyze glycemic trends, and track insulin treatments.

---

## What the Agent Does

- **Real-Time Continuous Glucose Monitoring (CGM)**: Fetches live sensor glucose readings (`mg/dL`) with trend trajectory arrows (`→`, `↗`, `↑`, `↘`, `↓`) and calculates rate-of-change deltas.
- **2-Hour Window Glycemic Analytics**: Analyzes recent glucose patterns to calculate average glucose, window extremes (min/max), and time-in-range percentage (TIR %) against personalized target ranges (e.g. 70–180 mg/dL).
- **Insulin & Treatment Tracking**: Inspects recent bolus deliveries (normal and combo/extended boluses), active temporary basal adjustments, and logged carbohydrate intakes from insulin pumps.
- **Rich A2UI Surfaces**: Formats glycemic trends and treatment logs into structured, interactive cards using the **A2UI v0.8** specification rendered directly within the conversation.
- **Real-Time Dashboard & AI Copilot**: Features a split-view frontend displaying live KPI stat cards, reading history timeline, and treatment logs alongside a nearby persistent Gemini AI Copilot.
- **Privacy & Credential Isolation**: Automatically masks API access tokens before passing profile data to the model (`[MASKED - CONFIGURED]`) and redacts sensitive credentials at the API proxy layer to prevent exposure in chats or DOM elements.

---

## Implemented Tools & Google Cloud Services

Based on `app/` and `agents-cli-manifest.yaml`, the following services and tools are implemented and wired up:

### 1. Google Cloud Services
- **Vertex AI Agent Runtime (Agent Engine)**: Hosts the deployed ADK agent running Gemini 3.6 Flash and exposes the A2A (Agent-to-Agent) communication protocol.
- **Google Cloud Firestore**: Persists user profiles, Nightscout host URLs, target glucose ranges (`target_low`, `target_high`), and credentials in the `nightscout_profiles` collection.
- **Vertex AI Code Sandbox (`AgentEngineSandboxCodeExecutor`)**: Executes isolated code and performs numerical and statistical calculations within a secure runtime.
- **A2UI (Agent-to-User Interface v0.8)**: Generates structured UI surfaces (`Card`, `Column`, `Row`, `Text`, `Divider`) using an `after_model_callback` transformer.

### 2. Agent Tools (`app/nightscout_tools.py`)
| Tool | Status | Description |
|---|---|---|
| `fetch_current_glucose(user_id)` | Implemented | Retrieves the latest CGM reading, delta, trend direction, and timestamp from Nightscout. |
| `fetch_glucose_trends(user_id, count=24)` | Implemented | Fetches historical readings to calculate 2-hour window statistics, TIR %, average, min/max, and timeline. |
| `fetch_recent_treatments(user_id, count=10)` | Implemented | Retrieves recent insulin boluses, active basal rates, and carbohydrate entries. |
| `get_nightscout_profile(user_id)` | Implemented | Loads the user's Nightscout profile and target range thresholds from Firestore with masked credentials. |
| `update_nightscout_profile(user_id, updates)` | Implemented | Updates target range boundaries, preferences, or instance configuration in Firestore. |

---

## Planned Capabilities (Not Yet Implemented)

The following features from the initial project brief are planned for future iterations and are not yet implemented in the current codebase:
- **Vertex AI Memory Bank**: Cross-session episodic and conversational memory extraction (currently, profiles and configurations are stored directly in Cloud Firestore).
- **Google Cloud Storage (GCS)**: Cloud bucket persistence for long-term data exports and file artifacts (in-memory artifact service is currently used).
- **Imagen / Image Generation**: Generating motivational badges, meal visualization, or milestone achievement graphics.

---

## Project Structure

```
nightscout-assistant/
├── app/
│   ├── agent.py               # Root ADK agent, system prompt, and A2UI schema manager
│   ├── nightscout_tools.py    # Nightscout REST API and Firestore profile integration
│   ├── a2ui_utils.py          # A2UI callback transformer and component sanitizer
│   ├── app_utils/             # A2A protocol and runtime helper utilities
│   └── __init__.py
├── frontend/
│   ├── main.py                # FastAPI proxy connecting browser to Agent Runtime via A2A
│   ├── static/index.html      # Responsive split dashboard with live stats & A2UI renderer
│   └── requirements.txt
├── agents-cli-manifest.yaml   # Agent deployment manifest (Agent Runtime, A2A enabled)
├── pyproject.toml             # Python dependencies (managed via uv)
└── README.md
```

---

## Local Setup & Run Instructions

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [Google Cloud SDK](https://cloud.google.com/sdk) installed and authenticated:
  ```bash
  gcloud auth application-default login
  ```

### 1. Run the Agent Locally (ADK Web)
To inspect and test the agent logic directly using the ADK development interface:
```bash
# Sync dependencies
uv sync

# Launch the ADK development web UI
uv run adk web app
```

### 2. Run the Dashboard Frontend Proxy
To launch the complete application with the live split dashboard and nearby AI Copilot:
```bash
cd frontend

# Set up virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure environment variables
export AGENT_ENGINE_RESOURCE_NAME="projects/<project-id>/locations/<region>/reasoningEngines/<engine-id>"
export AGENT_DIRECTORY="app"
export PORT=8080

# Start the frontend service
python main.py
```
Once started, navigate to the local server port in your web browser.

---

## Deployment

Deploy the agent to Vertex AI Agent Runtime using `agents-cli`:
```bash
agents-cli deploy --project <your-gcp-project-id> --region us-central1
```

