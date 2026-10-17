"""Rebuild the business PDF and instructional notebook from project sources."""
from pathlib import Path
from html import escape
import re
import nbformat as nbf
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether, PageBreak

ROOT = Path(__file__).resolve().parent


def build_pdf():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("BrandTitle", fontName="Helvetica-Bold", fontSize=24,
                              leading=28, textColor=colors.HexColor("#153b4a"), spaceAfter=12))
    styles.add(ParagraphStyle("SectionTitle", fontName="Helvetica-Bold", fontSize=12,
                              leading=16, textColor=colors.HexColor("#153b4a"), spaceBefore=14, spaceAfter=6))
    styles.add(ParagraphStyle("ProfileBody", fontName="Helvetica", fontSize=10,
                              leading=15, alignment=TA_LEFT, spaceAfter=7))
    doc = SimpleDocTemplate(str(ROOT / "me/about_business.pdf"), pagesize=A4,
                            leftMargin=46, rightMargin=46, topMargin=44, bottomMargin=44,
                            title="Cedar Compass Travel - Business Profile", author="Cedar Compass Travel (fictional)")
    sections = (ROOT / "me/business_profile.txt").read_text().split("\n\n")
    story = [Paragraph("Cedar Compass Travel", styles["BrandTitle"]),
             Paragraph("Business profile | Fictional course project", styles["ProfileBody"]),
             Spacer(1, 6)]
    for section in sections[1:]:
        title, *lines = section.splitlines()
        body = " ".join(lines)
        if title == "Services and policies":
            story.extend([PageBreak(), Paragraph("Services and customer follow-up", styles["BrandTitle"])])
        if title.startswith("Example packages"):
            story.append(Paragraph(escape(title), styles["SectionTitle"]))
            for package in re.split(r"(?=\b[123]\. )", body):
                if package.strip():
                    story.append(Paragraph(escape(package), styles["ProfileBody"]))
        else:
            story.append(KeepTogether([Paragraph(escape(title), styles["SectionTitle"]),
                                      Paragraph(escape(body), styles["ProfileBody"])]))

    def footer(canvas, document):
        canvas.setStrokeColor(colors.HexColor("#d5e0e4"))
        canvas.line(46, 35, A4[0]-46, 35)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#526872"))
        canvas.drawString(46, 23, "Simulated travel packages - no real bookings or live inventory")
        canvas.drawRightString(A4[0]-46, 23, str(document.page))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def build_notebook():
    md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
    cells = [
        md("# Cedar Compass Travel: agent-powered business assistant\n\n"
           "EECE 503P/798S - Class 3 assignment. This fictional travel agency uses the OpenAI API, "
           "explicit context-based LLM routing, genuine function calls, SQLite persistence, and reflection. "
           "Online hosting is deferred. Run this notebook from the `business_bot` directory."),
        md("## 1. Setup\n\nUse the environment created in the README. Select that environment as the notebook kernel. "
           "Copy `.env.example` to `.env` and set your API key locally. Never print or commit keys. "
           "An OpenAI API key is required for the live cells; the automated offline tests do not require one."),
        code("from pathlib import Path\nimport os, sys, json\nfrom uuid import uuid4\n"
             "PROJECT = Path.cwd()\nif not (PROJECT / 'agent.py').exists():\n    PROJECT = PROJECT / 'business_bot'\n"
             "assert (PROJECT / 'agent.py').exists(), 'Open the notebook from the project directory.'\n"
             "sys.path.insert(0, str(PROJECT))\nfrom dotenv import load_dotenv\nload_dotenv(PROJECT / '.env')\n"
             "print('API key configured:', bool(os.getenv('OPENAI_API_KEY')))"),
        md("## 2. Fictional business knowledge\n\nBoth the summary and the PDF are read into context. "
           "There is no document-search tool or vector database. The PDF is built from `me/business_profile.txt`."),
        code("from agent import load_business_context\nknowledge = load_business_context(PROJECT / 'me')\nprint(knowledge)"),
        md("## 3. Persona\n\nThe identity and tone are defined separately from operational rules."),
        code("from prompts import PERSONA\nprint(PERSONA)"),
        md("## 4. Instructions\n\nOperational guardrails govern facts, contact collection, tool use, and unsupported requests. "
           "Every unanswered business question starts name/email collection for staff review, without requiring "
           "a callback request. Answerable questions need no contact information; customers can decline."),
        code("from prompts import INSTRUCTIONS\nprint(INSTRUCTIONS)"),
        md("## 5. Explicit router\n\nThe LLM receives business knowledge and chat history and returns a validated intent. "
           "Python dispatches that intent to one of three handlers. No keyword rules choose the route. "
           "A short observable justification is logged; hidden reasoning is not requested."),
        code("from prompts import ROUTING_INSTRUCTIONS\nfrom schemas import RoutingDecision\nprint(ROUTING_INSTRUCTIONS)\nprint(json.dumps(RoutingDecision.model_json_schema(), indent=2))"),
        md("## 6. Tool definitions and persistence\n\n`record_customer_interest(email, name, message)` saves a lead; "
           "`record_feedback(question)` saves feedback or an unanswered question. Schemas below define names, "
           "parameters, and result contracts. Python executes actual model-returned `function_call` items and "
           "sends matching `function_call_output` items back to the model. SQLite records survive local restarts."),
        code("from schemas import TOOL_SCHEMAS\nprint(json.dumps(TOOL_SCHEMAS, indent=2))"),
        md("## 7. Construct the agent\n\nChoose the API model through `OPENAI_MODEL`. API calls use `store=False`; "
           "short-term history is passed by this application. The local database also persists demonstration traces."),
        code("from backend import OpenAIBackend\nfrom storage import Storage\nfrom agent import BusinessAgent\n"
             "assert os.getenv('OPENAI_API_KEY'), 'Set OPENAI_API_KEY in your local .env first.'\n"
             "db_path = Path(os.getenv('DATABASE_PATH', 'data/business.sqlite3'))\n"
             "if not db_path.is_absolute():\n    db_path = PROJECT / db_path\n"
             "storage = Storage(db_path)\nbackend = OpenAIBackend(os.getenv('OPENAI_MODEL', 'gpt-4o-mini'))\n"
             "agent = BusinessAgent(backend, storage, knowledge)"),
        md("## 8. Live conversations\n\nThis cell makes billable API calls. Every `ask` call prints the route, tool results, "
           "original draft, and revised reply. Only the revised reply enters customer-visible chat history."),
        code("history = []\nsession_id = str(uuid4())\n"
             "def ask(message):\n    result = agent.chat(message, history, session_id)\n"
             "    history.extend([{'role':'user','content':message}, {'role':'assistant','content':result.reply}])\n"
             "    print('Mira:', result.reply)\n    print(json.dumps(result.trace, indent=2, ensure_ascii=False))\n    return result"),
        code("ask('What is included in the Istanbul Culture Escape?')"),
        code("ask('I would like a quote for two adults visiting Istanbul in May.')"),
        code("ask('My name is Sam Haddad.')"),
        code("ask('My email is sam@example.com.')"),
        code("ask('Feedback: I wish you had more departure-date options.')"),
        md("### Unanswered question and automatic contact collection\n\nStart a fresh chat to demonstrate missing-contact "
           "collection without an explicit callback request. The question is logged first; the lead is saved once "
           "name and email are supplied. Staff review is not an automatic email or guaranteed callback."),
        code("history = []\nsession_id = str(uuid4())\nask('What is the single-room supplement for Jordan?')"),
        code("ask('Sam Haddad')"),
        code("ask('sam@example.com')"),
        md("## 9. Reflection bonus\n\nA separate model pass checks the draft against the same business facts, instructions, "
           "and successful/failed tool outcomes. It returns a final reply and concise issues. Original and revised "
           "replies are persisted. If it discovers an unlogged unknown question, a bounded correction requests the "
           "feedback tool and reflects again. Reflection itself cannot execute recording tools."),
        code("from prompts import REFLECTION_INSTRUCTIONS\nprint(REFLECTION_INSTRUCTIONS)\n"
             "reflections = [e for e in storage.records('events', 100) if e['event_type'] == 'reflection']\n"
             "for event in reflections[:3]:\n    print(json.dumps(json.loads(event['payload_json']), indent=2))"),
        md("## 10. Inspect saved records (owner/developer only)\n\nThese records are not displayed in the customer interface."),
        code("print('Leads:', json.dumps(storage.records('leads'), indent=2))\n"
             "print('Feedback:', json.dumps(storage.records('feedback'), indent=2))"),
        md("## 11. Gradio chatbot\n\nThe local UI uses `ChatInterface`, independent session state, and a development-only "
           "trace accordion. You can alternatively run `python app.py` in a terminal. No public sharing is enabled."),
        code("from app import build_app\nfrom ui import ui_launch_options\ndemo = build_app(agent)\ndemo.launch(server_name='127.0.0.1', share=False, **ui_launch_options())"),
        md("## 12. Validation and submission\n\nRun `python -m unittest discover -s tests -v` for meaningful offline tests. "
           "These validate persistence, tool round trips, session isolation, errors, and reflection with scripted "
           "model responses; they do not establish live model quality. Follow `DEMO.md` for live acceptance testing "
           "and the submission video. Submit the repo, this notebook, the business summary/PDF, and a video. "
           "Do not submit `.env` or customer database files. Online hosting remains deferred."),
    ]
    notebook = nbf.v4.new_notebook(cells=cells, metadata={
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    })
    nbf.write(notebook, ROOT / "business_agent.ipynb")


if __name__ == "__main__":
    build_pdf()
    build_notebook()
    print("Created me/about_business.pdf and business_agent.ipynb")
