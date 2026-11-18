# Autonomous Customer Order Resolution Agent

An autonomous ReAct tool-using agent built with the `google-genai` SDK that looks up order records, inspects warehouse inventory, conditionally executes exchanges or refunds, and dispatches customer confirmation emails.

## Setup & Run
1. `pip install -r requirements.txt`
2. `$env:GEMINI_API_KEY="your-api-key"`
3. `python resolution_agent.py`
