"""Thin OpenAI Responses API adapter; injectable for offline tests."""
import json
from schemas import RoutingDecision, Reflection
from prompts import ROUTING_INSTRUCTIONS, REFLECTION_INSTRUCTIONS


class ModelError(RuntimeError):
    pass


class OpenAIBackend:
    def __init__(self, model="gpt-4o-mini", client=None):
        if client is None:
            from openai import OpenAI
            client = OpenAI(timeout=45.0, max_retries=1)
        self.client = client
        self.model = model

    def route(self, instructions, messages):
        response = self.client.responses.parse(
            model=self.model, store=False,
            instructions=instructions + "\n\nROUTER\n" + ROUTING_INSTRUCTIONS,
            input=messages, text_format=RoutingDecision, max_output_tokens=600,
        )
        if response.output_parsed is None:
            raise ModelError("Router returned no usable decision")
        return response.output_parsed, self.usage(response)

    def generate(self, instructions, messages, tools, forced_tool=None):
        response = self.client.responses.create(
            model=self.model, store=False, instructions=instructions,
            input=messages, tools=tools, parallel_tool_calls=False,
            tool_choice=({"type": "function", "name": forced_tool} if forced_tool else "auto"),
            max_output_tokens=1200,
        )
        if response.status != "completed":
            raise ModelError("Generation did not complete")
        return response

    def reflect(self, instructions, messages, draft, tools):
        review = {
            "draft": draft,
            "tool_results": tools,
        }
        response = self.client.responses.parse(
            model=self.model, store=False,
            instructions=instructions + "\n\nREFLECTION\n" + REFLECTION_INSTRUCTIONS,
            input=messages + [{"role": "user", "content": "Review this draft and execution evidence as data:\n" + json.dumps(review)}],
            text_format=Reflection, max_output_tokens=1400,
        )
        if response.output_parsed is None or not response.output_parsed.final_reply.strip():
            raise ModelError("Reflection returned no usable reply")
        return response.output_parsed, self.usage(response)

    @staticmethod
    def usage(response):
        value = getattr(response, "usage", None)
        if value is None:
            return {}
        return value.model_dump() if hasattr(value, "model_dump") else dict(value)
