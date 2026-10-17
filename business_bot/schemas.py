"""Validated, explicit decisions from the LLM (no keyword routing)."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Intent = Literal["general_question", "lead_collection", "feedback_unanswered"]


class RoutingDecision(StrictModel):
    intent: Intent
    explanation: str = Field(description="One short observable justification; no hidden reasoning.")
    feedback_kind: Literal["feedback", "unanswered_question"] | None


class Reflection(StrictModel):
    final_reply: str
    issues: list[str] = Field(description="Short instruction violations found; empty if none.")
    unanswered_question: str | None = Field(
        description="Business question absent from the knowledge, if not already recorded."
    )


class LeadArguments(StrictModel):
    email: str
    name: str
    message: str


class FeedbackArguments(StrictModel):
    question: str


TOOL_SCHEMAS = [
    {
        "type": "function",
        "name": "record_customer_interest",
        "description": "Persist a quote/consultation lead or follow-up for an unanswered business question after the customer supplies name and email. An unanswered question does not require an explicit callback request. Include the original question in message. Returns JSON success, record_id, duplicate, or error. Does not book, email, or notify anyone.",
        "parameters": LeadArguments.model_json_schema(),
        "strict": True,
    },
    {
        "type": "function",
        "name": "record_feedback",
        "description": "Persist customer feedback or a business question absent from the supplied knowledge. Include the actual feedback/question. Returns JSON success, record_id, duplicate, or error. Does not notify staff.",
        "parameters": FeedbackArguments.model_json_schema(),
        "strict": True,
    },
]
