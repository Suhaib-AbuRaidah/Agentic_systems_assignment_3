"""Explicit context-based routing -> tools -> reflection -> persistent audit."""
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
from schemas import TOOL_SCHEMAS, LeadArguments, FeedbackArguments
from prompts import PERSONA, INSTRUCTIONS
from tools import RecordingTools

LOGGER = logging.getLogger(__name__)
PROJECT = Path(__file__).resolve().parent
MAX_MESSAGE_CHARS = 6000
HISTORY_MESSAGES = 24


def load_business_context(directory=PROJECT / "me"):
    from pypdf import PdfReader
    directory = Path(directory)
    summary = (directory / "business_summary.txt").read_text(encoding="utf-8")
    profile = "\n".join(page.extract_text() or "" for page in PdfReader(directory / "about_business.pdf").pages)
    if not profile.strip():
        raise ValueError("The business PDF has no readable text")
    return "BUSINESS SUMMARY\n" + summary + "\n\nBUSINESS PDF CONTENT\n" + profile


def message_text(value):
    """Accept Gradio text blocks; never add file paths or arbitrary objects."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            block.get("text", "") for block in value
            if isinstance(block, dict) and block.get("type") in {"text", "input_text", "output_text"}
        )
    return ""


def conversation(message, history):
    messages = []
    for item in (history or [])[-HISTORY_MESSAGES:]:
        if isinstance(item, dict) and item.get("role") in {"user", "assistant"}:
            content = message_text(item.get("content"))
            if content:
                messages.append({"role": item["role"], "content": content[:MAX_MESSAGE_CHARS]})
    messages.append({"role": "user", "content": message})
    return messages


@dataclass
class TurnResult:
    reply: str
    session_id: str
    trace: dict = field(default_factory=dict)


class BusinessAgent:
    def __init__(self, backend, storage, knowledge=None):
        self.backend = backend
        self.storage = storage
        self.knowledge = knowledge if knowledge is not None else load_business_context()
        self.system_prompt = "PERSONA\n" + PERSONA + "\n\nINSTRUCTIONS\n" + INSTRUCTIONS + "\n\n" + self.knowledge
        self.handlers = {
            "general_question": self.handle_general,
            "lead_collection": self.handle_lead,
            "feedback_unanswered": self.handle_feedback,
        }

    def chat(self, message, history=None, session_id=None):
        session_id = session_id or str(uuid4())
        turn_id = str(uuid4())
        trace = {"turn_id": turn_id, "route": None, "tools": [], "usage": []}
        message = message.strip() if isinstance(message, str) else ""
        if not message:
            return TurnResult("Please enter a travel question or message.", session_id, trace)
        if len(message) > MAX_MESSAGE_CHARS:
            return TurnResult("Please shorten your message to 6,000 characters or fewer.", session_id, trace)
        messages = conversation(message, history)
        try:
            # LLM chooses from context; Python only dispatches the validated enum.
            decision, usage = self.backend.route(self.system_prompt, messages)
            trace["route"] = decision.model_dump()
            trace["usage"].append({"stage": "routing", **usage})
            self.storage.event(session_id, turn_id, "routing", decision.model_dump())
            draft = self.handlers[decision.intent](decision, messages, session_id, turn_id, trace)
            trace["draft"] = draft
            self.storage.event(session_id, turn_id, "draft", {"reply": draft})
            reflection, usage = self.backend.reflect(self.system_prompt, messages, draft, trace["tools"])
            trace["usage"].append({"stage": "reflection", **usage})
            # If reflection catches an omitted unknown question, request a real
            # model-called tool, then review once more. Reflection itself has no tools.
            if reflection.unanswered_question and not self.feedback_saved(trace, reflection.unanswered_question):
                trace["reflection_correction"] = reflection.model_dump()
                self.storage.event(session_id, turn_id, "reflection_correction", reflection.model_dump())
                correction = self.system_prompt + "\nThe reviewer found an unanswered question. Call record_feedback for this question, then collect missing name/email or save its follow-up if contact details are complete. Respect refusal. Question: " + json.dumps(reflection.unanswered_question)
                draft = self.tool_loop(correction, messages, session_id, turn_id, trace, "unanswered_question", forced_tool="record_feedback", lead_allowed=False)
                trace["corrected_draft"] = draft
                reflection, usage = self.backend.reflect(self.system_prompt, messages, draft, trace["tools"])
                trace["usage"].append({"stage": "reflection_after_correction", **usage})
            if reflection.unanswered_question and not self.feedback_saved(trace, reflection.unanswered_question):
                raise RuntimeError("Unanswered question still not recorded")
            trace["reflection"] = reflection.model_dump()
            trace["revised_reply"] = reflection.final_reply
            self.storage.event(session_id, turn_id, "reflection", {"original_draft": trace["draft"], **reflection.model_dump()})
            return TurnResult(reflection.final_reply, session_id, trace)
        except Exception as error:
            # Provider response bodies, credentials, and stack traces stay out of UI.
            trace["error"] = type(error).__name__
            LOGGER.warning("Turn %s failed (%s)", turn_id, type(error).__name__)
            try:
                self.storage.event(session_id, turn_id, "error", {"type": type(error).__name__})
            except sqlite3.Error:
                pass
            saved = any(item["result"].get("success") for item in trace["tools"])
            reply = (
                "Your information was saved, but I couldn't finish the reply. Please try your question again."
                if saved else "I couldn't complete your request. Please try again shortly."
            )
            return TurnResult(reply, session_id, trace)

    @staticmethod
    def feedback_saved(trace, question):
        normalized = " ".join(question.casefold().split())
        return any(
            item["name"] == "record_feedback" and item["result"].get("success")
            and item.get("feedback_kind") == "unanswered_question"
            and " ".join(item["arguments"]["question"].casefold().split()) == normalized
            for item in trace["tools"]
        )

    def handle_general(self, decision, messages, session_id, turn_id, trace):
        instructions = self.system_prompt + "\nRoute: general_question. Answer from the profile. If you discover a missing business answer, record it and begin name/email collection for staff review, respecting refusal. Do not collect contact for an answerable question."
        return self.tool_loop(instructions, messages, session_id, turn_id, trace, "unanswered_question", lead_allowed=False)

    def handle_lead(self, decision, messages, session_id, turn_id, trace):
        instructions = self.system_prompt + "\nRoute: lead_collection. Use history; ask only for missing contact details, or record interest when complete. An unanswered question starts this flow automatically, without a customer callback request. Include that original question in the lead notes; do not relog it if already recorded. Respect refusal."
        return self.tool_loop(instructions, messages, session_id, turn_id, trace, "unanswered_question")

    def handle_feedback(self, decision, messages, session_id, turn_id, trace):
        instructions = self.system_prompt + "\nRoute: feedback_unanswered. Record the relevant feedback or unanswered business question before replying. For an unanswered question, then ask for missing name/email for staff review or record its follow-up when both are already supplied. Do not require a customer callback request. Respect refusal. Pure feedback alone does not require contact collection."
        return self.tool_loop(instructions, messages, session_id, turn_id, trace, decision.feedback_kind or "feedback", forced_tool="record_feedback")

    def tool_loop(self, instructions, messages, session_id, turn_id, trace, feedback_kind, forced_tool=None, lead_allowed=True):
        context = list(messages)
        for step in range(5):
            # A general answer or reflection repair can discover an unknown
            # question. After logging it, let the LLM save supplied contact
            # details without requiring a new customer-requested follow-up.
            if not lead_allowed and any(
                item["name"] == "record_feedback"
                and item.get("feedback_kind") == "unanswered_question"
                and item["result"].get("success") for item in trace["tools"]
            ):
                lead_allowed = True
            tools = [tool for tool in TOOL_SCHEMAS if lead_allowed or tool["name"] != "record_customer_interest"]
            response = self.backend.generate(instructions, context, tools, forced_tool if step == 0 else None)
            trace["usage"].append({"stage": "generation", **self.backend.usage(response)})
            calls = [item for item in response.output if item.type == "function_call"]
            if step == 0 and forced_tool and not any(call.name == forced_tool for call in calls):
                raise RuntimeError("Required recording tool was not requested")
            # Keep all output items, including reasoning, for tool continuation.
            context.extend(item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else vars(item) for item in response.output)
            if not calls:
                if not response.output_text.strip():
                    raise RuntimeError("Model returned no draft")
                return response.output_text
            for call in calls:
                try:
                    arguments = json.loads(call.arguments)
                except (ValueError, TypeError):
                    arguments = None
                result = self.execute_tool(call.name, arguments, messages, session_id, turn_id, feedback_kind, lead_allowed)
                evidence = {"name": call.name, "arguments": arguments, "result": result}
                if call.name == "record_feedback":
                    evidence["feedback_kind"] = feedback_kind
                trace["tools"].append(evidence)
                self.storage.event(session_id, turn_id, "tool_call", evidence)
                context.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result)})
        raise RuntimeError("Tool-call limit reached")

    def execute_tool(self, name, arguments, messages, session_id, turn_id, feedback_kind, lead_allowed):
        try:
            recording = RecordingTools(self.storage, session_id, turn_id, feedback_kind)
            if name == "record_customer_interest" and lead_allowed:
                args = LeadArguments.model_validate(arguments)
                email, customer_name, notes = args.email.strip(), args.name.strip(), args.message.strip()
                # Regex is only email validation; it plays no part in routing.
                if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
                    return {"success": False, "error": "Please ask the customer for a valid email address."}
                if not customer_name or len(customer_name) > 120 or not notes or len(notes) > 6000:
                    return {"success": False, "error": "A name and concise travel-interest notes are required."}
                supplied = "\n".join(item["content"] for item in messages if item["role"] == "user").casefold()
                if email.casefold() not in supplied or customer_name.casefold() not in supplied:
                    return {"success": False, "error": "Use only name and email explicitly supplied by this customer."}
                return recording.record_customer_interest(email.casefold(), customer_name, notes)
            if name == "record_feedback":
                args = FeedbackArguments.model_validate(arguments)
                question = args.question.strip()
                if not question or len(question) > 6000:
                    return {"success": False, "error": "Include the actual feedback or unanswered question (1-6000 characters)."}
                return recording.record_feedback(question)
            return {"success": False, "error": "This tool is not available on the selected route."}
        except (ValidationError, TypeError, ValueError):
            return {"success": False, "error": "Tool arguments did not match the documented schema."}
        except sqlite3.Error:
            return {"success": False, "error": "The local database could not save the record. Do not claim it was saved."}
