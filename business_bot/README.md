# Cedar Compass Travel

A local business chatbot for the Class 3 agent assignment. Mira represents a
fictional travel agency. It uses the **OpenAI API** (the API backend for GPT
models), not the ChatGPT website. Online deployment is deferred.

## Video demonstration

![Looping 3-minute Cedar Compass demo](Demo.gif)

[Download the full-quality demo with audio (MP4)](Demo.mp4?raw=1)

The GIF loops without audio; the MP4 retains full quality and audio. The
recording shows the local interface and a live conversation. The saved
records and tool decisions are explained below and in `DEMO.md`.

## Run locally

Run these commands from the `business_bot` directory. Python 3.12 is the tested
version. The project virtual environment has already been installed in this
workspace; on another computer create it first:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Open `.env` locally and set `OPENAI_API_KEY` to your OpenAI API key. Keep it out
of the notebook and GitHub. `OPENAI_MODEL` defaults to `gpt-4o-mini`, with support
for Responses API function calling and structured output; it is configurable.
The app requires internet access to call OpenAI even while running locally.

```bash
python app.py
```

Open **http://127.0.0.1:7860**. The app binds to your own computer and uses
`share=False`. It can start without a key and will display a setup message when
you submit a chat; live routing, answers, and reflection require a valid key.
API model calls consume your API usage. There is no pretend/offline customer
answering mode in the app.

## Interface assets

The interface includes a branded travel header, three illustrated package
cards, and a coordinated chat panel. The assignment trace is collapsed below
the conversation. The layout adapts to smaller screens and supports light and
dark mode.

`assets/editorial.css` copies and adapts the Editorial palette and styling
from the local Ultra Explainer template. Its MIT license is included in
`assets/ULTRAEXPLAINER-LICENSE.txt`. The HTML, CSS, and inline SVG illustrations
are bundled inside this project; the original `Template` folder is not needed
when delivering or running it. System fonts avoid external font downloads.
The interface adds no model calls or new Python dependencies.

`app.py` and the notebook both use `ui_launch_options()` for Gradio 6's launch
theme/CSS settings. Use that helper too if you write another launch script.

## Agent flow

```text
Customer message + this session's recent history
    -> LLM router (structured intent + short justification)
    -> Python dispatches general / lead / feedback-unanswered handler
    -> LLM answers or requests actual recording tool calls
    -> Python validates tool arguments and writes SQLite records
    -> Tool execution results go back to the model
    -> Draft reply
    -> LLM reflection checks facts, instructions, and tool outcomes
    -> Revised customer reply
```

The same configured model handles the stages. Routing is an explicit LLM
classification using conversation context, not keyword matching. The model
receives both the summary and extracted business PDF text. No search tools,
embeddings, or vector stores are used. A known question does not demand contact
information. Every unanswered business question automatically starts contact
collection for staff review: Mira logs the question, asks for a missing name
then email, and saves a lead containing the original question once both are
supplied. The customer does not need to request a callback first. Existing
contact details in the same conversation are reused. Customers can decline;
the question remains logged without a lead. Pure feedback alone does not
require contact collection. Saving records does not send email or notify staff.

`PERSONA` and `INSTRUCTIONS` are separate constants in `prompts.py`, then
assembled into `system_prompt`. Business data is fictional and editable in
`me/business_profile.txt` and `me/business_summary.txt`. When editing business
facts, keep those files consistent and rebuild the PDF:

```bash
python build_artifacts.py
```

This also rebuilds the explanatory notebook, so preserve any notebook changes
you want to keep before rerunning it.

## Routes and tools

| Route | Handling |
|---|---|
| `general_question` | Answer from supplied knowledge; feedback tool is available if the handler discovers a missing answer. |
| `lead_collection` | Continue quote/consultation or unanswered-question contact collection, including name/email-only replies. Ask for missing fields, then request the lead tool with the original question in its notes. Respect refusal. |
| `feedback_unanswered` | Require the feedback tool first. For unanswered questions, start contact collection or save a lead if contact details are already supplied. Pure feedback needs no contact request. |

The router also identifies `feedback` versus `unanswered_question`. Python
validates the intent through a Pydantic schema. Invalid/refused model outputs
produce an error response; no keyword fallback silently guesses a route.

| Tool | Parameters | Result |
|---|---|---|
| `record_customer_interest` | `email: str`, `name: str`, `message: str` (travel-interest notes) | `{"success": true, "record_id": integer, "duplicate": boolean}`, or `{"success": false, "error": string}` |
| `record_feedback` | `question: str` (feedback or unknown business question) | Same success/error contract. |

The tool schemas are in `schemas.py`; `agent.py` validates and dispatches calls
to the two recording functions in `tools.py`. The model
actually emits function calls, and Python sends matching results back. A tool
does not book, take payment, send email, or notify staff. Regex is used only for
email validation and never for intent routing. Contact names/emails must appear
in this customer's supplied messages before the lead tool can save them.

## Structured, persistent storage

SQLite creates `data/business.sqlite3` on the first configured conversation.
The file persists across ordinary local app/computer restarts. Its location is
configurable through `DATABASE_PATH`; relative paths use this project directory.

| Table | Structured fields |
|---|---|
| `leads` | ID, UTC timestamp, session/turn IDs, email, name, interest notes, idempotency key |
| `feedback` | ID, UTC timestamp, session/turn IDs, kind, feedback/question, idempotency key |
| `events` | ID, UTC timestamp, session/turn IDs, event type, JSON payload |

Event payloads include route decisions, tool arguments/results, usage counters,
original drafts, final replies, reflection issues, and safe error types. They
can contain the customer's contact details. The database is excluded from Git.
Identical tool writes in the same turn are idempotent. This is not global lead
deduplication: a new inquiry in a new turn may create a new record.

Use these **owner/developer CLI commands** to inspect records:

```bash
python inspect_records.py leads
python inspect_records.py feedback
python inspect_records.py events --limit 30
```

There is no customer-facing endpoint for listing stored records. The local
assignment UI has a collapsed trace accordion showing only that session's
latest turn. Remove it before any future customer-facing deployment.

Chat history is session-scoped short-term memory (latest 24 messages), not
reloaded from the database after a refresh. Saved leads/feedback remain after
chat clearing. A restarted/refreshed chat does not automatically recognize an
earlier customer. SQLite persistence and conversation memory are separate.

## Reflection bonus

Every successful turn has a separate review pass against instructions, full
business knowledge, and actual tool results. The original draft and revised
reply are both logged, along with concise issues. Reflection is a visible
instruction check; it does not request hidden reasoning. It cannot execute
tools. If it discovers an unlogged unknown question, a bounded correction
requests the model's feedback tool and then reviews the new draft again.
If the general handler or reflection repair logs an unanswered question,
the next tool step also permits saving a lead with supplied contact details.
The review checks for a missing name/email question and avoids unsupported
callback promises.

An ordinary turn normally uses three API requests: routing, draft, reflection.
Tool continuations add requests. The business context is included in each
stage; context and outputs consume tokens. Each response's usage is included
in the trace so the actual counts can be inspected. Reflection improves
instruction checking but is not a proof that model answers are always correct.

## Notebook and validation

Open `business_agent.ipynb` using the project's Python environment as the kernel.
For Jupyter setup, install `ipykernel` into that environment if your editor
requires it. The notebook imports the same implementation as `app.py` rather
than duplicating logic; it explains all stages and includes live demonstration
cells. Running those cells requires the configured API key and consumes API usage.

```bash
python -m unittest discover -s tests -v
```

Offline tests use scripted model responses. They cover tool-call continuations,
context forwarding, persistent storage across a fresh process, session
isolation, idempotency, invalid contact fields, failed database writes,
reflection correction, and safe API errors. They do **not** demonstrate the
real LLM's classification accuracy. Follow `DEMO.md` for live acceptance checks.

## Submission files

```text
business_bot/
  me/about_business.pdf
  me/business_summary.txt
  me/business_profile.txt
  business_agent.ipynb
  app.py
  agent.py / backend.py / prompts.py / schemas.py / storage.py / tools.py
  inspect_records.py / build_artifacts.py
  requirements.txt / requirements.lock.txt
  README.md / DEMO.md
  Demo.mp4 / Demo.gif
  assets/demo-preview.jpg
  tests/test_agent.py
  .env.example / .gitignore
```

Submit the repository and demonstration video. Keep `.env`, the virtual
environment, and actual database records out of the repository. Online hosting
of the app is deferred. A future host must provide persistent storage if
records are to survive replacement of its application environment.

## Official references

- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Gradio ChatInterface](https://www.gradio.app/docs/gradio/chatinterface)
