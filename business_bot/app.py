"""Local Gradio customer chat, with a development-only trace viewer."""
import logging
import os
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
import gradio as gr
from dotenv import load_dotenv

from agent import BusinessAgent, PROJECT
from backend import OpenAIBackend
from storage import Storage
from ui import asset_text, ui_launch_options

load_dotenv(PROJECT / ".env")
_agent = None


def database_path():
    path = Path(os.getenv("DATABASE_PATH", "data/business.sqlite3"))
    return path if path.is_absolute() else PROJECT / path


def get_agent():
    global _agent
    if _agent is None:
        _agent = BusinessAgent(OpenAIBackend(os.getenv("OPENAI_MODEL", "gpt-4o-mini")), Storage(database_path()))
    return _agent


def build_app(agent=None):
    def respond(message, history, session_id):
        session_id = session_id or str(uuid4())
        if agent is None and not os.getenv("OPENAI_API_KEY"):
            return (
                "The chatbot isn't configured yet. Add your OpenAI API key to the local .env file and restart the app.",
                session_id, {"status": "API key not configured"},
            )
        try:
            result = (agent or get_agent()).chat(message, history, session_id)
            return result.reply, result.session_id, result.trace
        except Exception as error:
            logging.getLogger(__name__).warning("App initialization failed (%s)", type(error).__name__)
            return "The chatbot couldn't start. Check the local setup and try again.", session_id, {"status": "Setup error", "error": type(error).__name__}

    with gr.Blocks(title="Cedar Compass Travel | Mira") as demo:
        gr.HTML(asset_text("header.html"), apply_default_css=False)
        gr.HTML(asset_text("packages.html"), apply_default_css=False)
        session = gr.State(value=lambda: str(uuid4()))
        trace = gr.JSON(label="Latest turn", render=False)
        with gr.Column(elem_id="cc-chat-section"):
            gr.HTML(
                '<div class="cc-chat-heading"><span class="cc-mira-badge" aria-hidden="true">M</span>'
                '<div><h2>Where shall we go?</h2><p>Ask Mira about a trip, request a quote, or share your feedback.</p></div></div>',
                apply_default_css=False,
            )
            chatbot = gr.Chatbot(
                height=390, show_label=False, elem_id="cc-chatbot",
                placeholder='<div class="cc-welcome"><div class="cc-welcome-mark">M</div>'
                            '<h3>Hello, I’m Mira.</h3><p>Tell me what you love about traveling.<br>'
                            'We can explore the details together.</p></div>',
            )
            textbox = gr.Textbox(
                placeholder="Ask about a destination, package, or your next trip…",
                show_label=False, container=False, elem_id="cc-message",
                submit_btn="Send", stop_btn="Stop",
            )
            gr.ChatInterface(
                respond, chatbot=chatbot, textbox=textbox,
                additional_inputs=[session], additional_outputs=[session, trace],
                examples=[
                    ["What does the Istanbul Culture Escape include?", None],
                    ["I'd like a quote for two people traveling to Jordan.", None],
                    ["I have some feedback about your packages.", None],
                    ["What is the single-room supplement?", None],
                ], examples_label="A few places to start", cache_examples=False,
                autofocus=False, api_name="chat",
            )
            gr.Markdown("For a quote or an unanswered business question, Mira asks for your name and email for staff review. "
                        "You can decline to share contact details. "
                        "Your interest and feedback are saved locally for this course project. "
                        "Saving a request does not send an email or confirm a booking.", elem_id="cc-privacy")
        chatbot.clear(lambda: (str(uuid4()), {}), outputs=[session, trace])
        with gr.Accordion("Assignment demo · Route, tools & reflection", open=False, elem_id="cc-trace"):
            trace.render()
            gr.Markdown("Development view for your own conversation. Saved customer records are inspected separately by the owner.")
        gr.Markdown("**Cedar Compass Travel** · Beirut, Lebanon  \n"
                    "Fictional agency for a course assignment. Package prices are examples; bookings require staff confirmation.",
                    elem_id="cc-footer")
    return demo


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    demo = build_app()
    demo.queue(default_concurrency_limit=4).launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        share=False, allowed_paths=[], **ui_launch_options(),
    )
