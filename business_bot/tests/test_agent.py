"""Offline orchestration tests. Scripted responses are not live LLM evaluations."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent import BusinessAgent, conversation, load_business_context
from backend import OpenAIBackend
from schemas import RoutingDecision, Reflection
from storage import Storage


def response(text="", tool=None, args=None, call_id="call_1"):
    items = []
    if tool:
        items.append(SimpleNamespace(type="function_call", name=tool,
                                    arguments=json.dumps(args), call_id=call_id))
    return SimpleNamespace(output=items, output_text=text, status="completed", usage=None)


class ScriptedBackend:
    def __init__(self, intent="general_question", generations=None, reflections=None, kind=None):
        self.decision = RoutingDecision(intent=intent, explanation="Scripted test decision.", feedback_kind=kind)
        self.generations = iter(generations or [response("Example draft")])
        self.reflections = iter(reflections or [Reflection(final_reply="Reviewed reply", issues=[], unanswered_question=None)])
        self.requests = []
        self.routing_input = None
        self.review_drafts = []

    def route(self, instructions, messages):
        self.routing_input = messages
        return self.decision, {}

    def generate(self, instructions, messages, tools, forced_tool=None):
        self.requests.append({"messages": list(messages), "forced_tool": forced_tool, "tools": tools})
        return next(self.generations)

    def reflect(self, instructions, messages, draft, tools):
        self.review_drafts.append(draft)
        return next(self.reflections), {}

    usage = staticmethod(lambda response: {})


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "records.sqlite3"
        self.db = Storage(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, backend):
        return BusinessAgent(backend, self.db, "Example business: Istanbul USD 790; single supplements unpublished.")

    def test_known_question_no_tools_and_reflection_is_visible(self):
        model = ScriptedBackend(generations=[response("Incorrect draft")], reflections=[
            Reflection(final_reply="The example price is USD 790.", issues=["Corrected unsupported price"], unanswered_question=None)
        ])
        result = self.agent(model).chat("How much is Istanbul?")
        self.assertEqual(result.trace["route"]["intent"], "general_question")
        self.assertEqual(result.trace["draft"], "Incorrect draft")
        self.assertEqual(result.reply, "The example price is USD 790.")
        self.assertEqual(self.db.records("leads"), [])
        self.assertEqual(self.db.records("feedback"), [])
        self.assertIn("reflection", [event["event_type"] for event in self.db.records("events")])

    def test_partial_contact_uses_history_and_real_tool_round_trip(self):
        history = [
            {"role": "user", "content": "I want an Istanbul quote for two. My name is Sam Haddad."},
            {"role": "assistant", "content": "What email can I record for follow-up?"},
        ]
        args = {"email": "sam@example.com", "name": "Sam Haddad", "message": "Istanbul quote for two"}
        model = ScriptedBackend("lead_collection", [response(tool="record_customer_interest", args=args), response("Saved")])
        result = self.agent(model).chat("sam@example.com", history, "customer-a")
        self.assertEqual(model.routing_input[0], history[0])
        self.assertEqual(self.db.records("leads")[0]["email"], "sam@example.com")
        output = model.requests[1]["messages"][-1]
        self.assertEqual(output["type"], "function_call_output")
        self.assertEqual(output["call_id"], "call_1")
        self.assertTrue(json.loads(output["output"])["success"])
        self.assertTrue(result.trace["tools"][0]["result"]["success"])

    def test_incomplete_lead_does_not_create_record(self):
        model = ScriptedBackend("lead_collection", [response("What is your name?")])
        self.agent(model).chat("Please arrange a quote")
        self.assertEqual(self.db.records("leads"), [])

    def test_feedback_and_unknown_question_are_distinct(self):
        for kind in ["feedback", "unanswered_question"]:
            model = ScriptedBackend("feedback_unanswered", [
                response(tool="record_feedback", args={"question": "single-room supplement?"}), response("Recorded")
            ], kind=kind)
            self.agent(model).chat("single-room supplement?")
            self.assertEqual(model.requests[0]["forced_tool"], "record_feedback")
        self.assertEqual({r["kind"] for r in self.db.records("feedback")}, {"feedback", "unanswered_question"})

    def test_unknown_question_collects_contact_across_turns_without_callback_request(self):
        question = "What is the single-room supplement for Jordan?"
        history = []
        session = "unanswered-customer"
        stages = [
            (question, ScriptedBackend("feedback_unanswered", [
                response(tool="record_feedback", args={"question": question}),
                response("Staff confirmation is needed. What name should I attach to your question?"),
            ], [Reflection(final_reply="Staff confirmation is needed. What name should I attach to your question?",
                           issues=[], unanswered_question=None)], kind="unanswered_question")),
            ("Sam Haddad", ScriptedBackend("lead_collection", [response("What email should I record?")],
                [Reflection(final_reply="What email should I record?", issues=[], unanswered_question=None)])),
            ("sam@example.com", ScriptedBackend("lead_collection", [
                response(tool="record_customer_interest", args={"name": "Sam Haddad", "email": "sam@example.com",
                         "message": question}), response("Your contact details and question are saved for staff review."),
            ], [Reflection(final_reply="Your contact details and question are saved for staff review.",
                           issues=[], unanswered_question=None)])),
        ]
        for index, (message, model) in enumerate(stages):
            result = self.agent(model).chat(message, history, session)
            self.assertNotIn("error", result.trace)
            self.assertEqual(model.routing_input, history + [{"role": "user", "content": message}])
            if index < 2:
                self.assertEqual(self.db.records("leads"), [])
            history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": result.reply}])
        self.assertEqual(len(self.db.records("feedback")), 1)
        self.assertEqual(self.db.records("feedback")[0]["kind"], "unanswered_question")
        lead = self.db.records("leads")[0]
        self.assertEqual((lead["name"], lead["email"], lead["message"]), ("Sam Haddad", "sam@example.com", question))
        self.assertEqual(lead["session_id"], session)

    def test_unknown_question_reuses_contact_and_saves_both_records(self):
        question = "What is the single-room supplement?"
        model = ScriptedBackend("feedback_unanswered", [
            response(tool="record_feedback", args={"question": question}),
            response(tool="record_customer_interest", args={"name": "Sam", "email": "sam@example.com", "message": question}),
            response("Question and contact saved."),
        ], kind="unanswered_question")
        history = [{"role": "user", "content": "My name is Sam and my email is sam@example.com."}]
        result = self.agent(model).chat(question, history)
        self.assertNotIn("error", result.trace)
        self.assertEqual(model.requests[0]["forced_tool"], "record_feedback")
        self.assertEqual(len(self.db.records("feedback")), 1)
        self.assertEqual(self.db.records("leads")[0]["message"], question)
        self.assertTrue(all(call["result"]["success"] for call in result.trace["tools"]))

    def test_general_handler_can_save_contact_after_discovering_unknown(self):
        question = "What is the single-room supplement?"
        model = ScriptedBackend("general_question", [
            response(tool="record_feedback", args={"question": question}),
            response(tool="record_customer_interest", args={"name": "Sam", "email": "sam@example.com", "message": question}),
            response("Question and contact saved."),
        ])
        result = self.agent(model).chat("I'm Sam, sam@example.com. " + question)
        self.assertNotIn("error", result.trace)
        self.assertNotIn("record_customer_interest", [tool["name"] for tool in model.requests[0]["tools"]])
        self.assertIn("record_customer_interest", [tool["name"] for tool in model.requests[1]["tools"]])
        self.assertEqual(len(self.db.records("feedback")), 1)
        self.assertEqual(self.db.records("leads")[0]["message"], question)

    def test_reflection_repair_can_record_unknown_and_complete_contact(self):
        question = "What is the single-room supplement?"
        model = ScriptedBackend(generations=[
            response("I don't know."),
            response(tool="record_feedback", args={"question": question}),
            response(tool="record_customer_interest", args={"name": "Sam", "email": "sam@example.com", "message": question}),
            response("Question and contact saved."),
        ], reflections=[
            Reflection(final_reply="I don't know.", issues=["Missing unknown log"], unanswered_question=question),
            Reflection(final_reply="Question and contact saved for staff review.", issues=[], unanswered_question=None),
        ])
        result = self.agent(model).chat("I'm Sam, sam@example.com. " + question)
        self.assertNotIn("error", result.trace)
        self.assertIn("reflection_correction", result.trace)
        self.assertEqual(model.requests[1]["forced_tool"], "record_feedback")
        self.assertIn("record_customer_interest", [tool["name"] for tool in model.requests[2]["tools"]])
        self.assertEqual(len(self.db.records("feedback")), 1)
        self.assertEqual(self.db.records("leads")[0]["message"], question)

    def test_contact_refusal_keeps_unanswered_question_without_lead(self):
        question = "What is the single-room supplement?"
        first = ScriptedBackend("feedback_unanswered", [
            response(tool="record_feedback", args={"question": question}), response("What name should I attach?"),
        ], [Reflection(final_reply="What name should I attach?", issues=[], unanswered_question=None)], kind="unanswered_question")
        result = self.agent(first).chat(question, session_id="declining-customer")
        history = [{"role": "user", "content": question}, {"role": "assistant", "content": result.reply}]
        second = ScriptedBackend("lead_collection", [response("You can keep your contact details private.")])
        result = self.agent(second).chat("I don't want to give my name or email.", history, result.session_id)
        self.assertNotIn("error", result.trace)
        self.assertEqual(len(self.db.records("feedback")), 1)
        self.assertEqual(self.db.records("leads"), [])

    def test_identical_tool_retry_writes_once(self):
        args = {"email": "sam@example.com", "name": "Sam", "message": "Jordan quote"}
        model = ScriptedBackend("lead_collection", [
            response(tool="record_customer_interest", args=args),
            response(tool="record_customer_interest", args=args, call_id="call_2"), response("Saved")
        ])
        result = self.agent(model).chat("I'm Sam, sam@example.com. Please quote Jordan.")
        self.assertEqual(len(self.db.records("leads")), 1)
        self.assertTrue(result.trace["tools"][1]["result"]["duplicate"])

    def test_invalid_email_and_invented_contact_are_rejected(self):
        for email in ["not-an-email", "invented@example.com"]:
            model = ScriptedBackend("lead_collection", [
                response(tool="record_customer_interest", args={"email": email, "name": "Sam", "message": "Trip"}),
                response("Please correct the email")
            ])
            result = self.agent(model).chat("I'm Sam. Contact me at not-an-email.")
            self.assertFalse(result.trace["tools"][0]["result"]["success"])
        self.assertEqual(self.db.records("leads"), [])

    def test_database_failure_returned_to_model_without_false_success(self):
        model = ScriptedBackend("feedback_unanswered", [
            response(tool="record_feedback", args={"question": "More destinations please"}), response("Could not save")
        ], kind="feedback")
        with patch.object(self.db, "save_feedback", side_effect=sqlite3.OperationalError("disk full")):
            result = self.agent(model).chat("More destinations please")
        self.assertFalse(result.trace["tools"][0]["result"]["success"])
        self.assertFalse(json.loads(model.requests[1]["messages"][-1]["output"])["success"])

    def test_missing_unknown_logging_found_by_reflection_runs_tool(self):
        model = ScriptedBackend(generations=[
            response("I don't know"),
            response(tool="record_feedback", args={"question": "Single supplement?"}), response("Recorded question")
        ], reflections=[
            Reflection(final_reply="I don't know", issues=["Unlogged question"], unanswered_question="Single supplement?"),
            Reflection(final_reply="I logged your question for staff review.", issues=[], unanswered_question=None),
        ])
        result = self.agent(model).chat("Single supplement?")
        self.assertEqual(len(self.db.records("feedback")), 1)
        self.assertEqual(self.db.records("feedback")[0]["kind"], "unanswered_question")
        self.assertEqual(len(model.review_drafts), 2)
        self.assertIn("reflection_correction", result.trace)

    def test_api_error_never_leaks_sensitive_exception_text(self):
        model = ScriptedBackend()
        model.route = lambda *args: (_ for _ in ()).throw(RuntimeError("SECRET-like-provider-message"))
        result = self.agent(model).chat("Hello")
        self.assertNotIn("SECRET", result.reply + json.dumps(result.trace))
        self.assertEqual(result.trace["error"], "RuntimeError")

    def test_logged_feedback_does_not_hide_a_different_unknown_question(self):
        model = ScriptedBackend("feedback_unanswered", generations=[
            response(tool="record_feedback", args={"question": "I want more free time"}),
            response("Thanks; I cannot quote single rooms"),
            response(tool="record_feedback", args={"question": "Single supplement?"}),
            response("Both recorded"),
        ], reflections=[
            Reflection(final_reply="Unknown", issues=["Missing unknown log"], unanswered_question="Single supplement?"),
            Reflection(final_reply="Both recorded", issues=[], unanswered_question=None),
        ], kind="feedback")
        self.agent(model).chat("More free time please; what is the single supplement?")
        self.assertEqual(len(self.db.records("feedback")), 2)
        self.assertEqual({r["kind"] for r in self.db.records("feedback")}, {"feedback", "unanswered_question"})

    def test_records_survive_a_fresh_python_process(self):
        self.db.save_feedback("s", "t", "key", "feedback", "Great itinerary")
        script = "from storage import Storage; import sys; print(Storage(sys.argv[1]).records('feedback')[0]['question'])"
        result = subprocess.run([sys.executable, "-c", script, str(self.path)], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "Great itinerary")

    def test_separate_sessions_do_not_share_chat_history(self):
        model = ScriptedBackend("lead_collection", generations=[response("First"), response("Second")], reflections=[
            Reflection(final_reply="First", issues=[], unanswered_question=None),
            Reflection(final_reply="Second", issues=[], unanswered_question=None),
        ])
        agent = self.agent(model)
        first = agent.chat("I'm Sam", session_id="first")
        second = agent.chat("Hello", session_id="second")
        self.assertEqual(model.routing_input, [{"role": "user", "content": "Hello"}])
        self.assertNotEqual(first.session_id, second.session_id)

    def test_gradio_text_blocks_are_supported_and_files_ignored(self):
        history = [{"role": "user", "content": [{"type": "text", "text": "Sam"}, {"type": "file", "path": "/secret"}]}]
        self.assertEqual(conversation("Email", history)[0]["content"], "Sam")

    def test_pdf_and_summary_are_loaded(self):
        context = load_business_context()
        self.assertIn("BUSINESS PDF CONTENT", context)
        self.assertIn("BUSINESS SUMMARY", context)
        for fact in ["420", "790", "680", "Cancellation", "Petra", "30%"]:
            self.assertIn(fact, context)

    def test_openai_adapter_request_contracts(self):
        from unittest.mock import Mock
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=RoutingDecision(
            intent="general_question", explanation="Question", feedback_kind=None), usage=None)
        backend = OpenAIBackend(client=client)
        backend.route("facts", [{"role": "user", "content": "Hello"}])
        kwargs = client.responses.parse.call_args.kwargs
        self.assertFalse(kwargs["store"])
        self.assertIs(kwargs["text_format"], RoutingDecision)
        client.responses.create.return_value = response("Draft")
        backend.generate("facts", [], [], "record_feedback")
        self.assertEqual(client.responses.create.call_args.kwargs["tool_choice"], {"type": "function", "name": "record_feedback"})

    def test_real_sdk_parse_and_tool_continuation_with_mock_http(self):
        import httpx
        from openai import OpenAI
        requests = []
        lead = {"name": "Sam", "email": "sam@example.com", "message": "Jordan quote"}
        outputs = [
            {"intent": "lead_collection", "explanation": "Customer supplies contact for a quote.", "feedback_kind": None},
            None,
            "I saved your interest in Jordan.",
            {"final_reply": "I saved your interest in Jordan for staff review.", "issues": [], "unanswered_question": None},
        ]

        def http_handler(request):
            body = json.loads(request.content)
            requests.append(body)
            index = len(requests) - 1
            if index == 1:
                output = [{"type": "function_call", "id": "fc_test", "status": "completed",
                           "name": "record_customer_interest", "call_id": "call_test", "arguments": json.dumps(lead)}]
            else:
                text = json.dumps(outputs[index]) if isinstance(outputs[index], dict) else outputs[index]
                output = [{"type": "message", "id": "msg_test", "status": "completed", "role": "assistant",
                           "content": [{"type": "output_text", "text": text, "annotations": []}]}]
            return httpx.Response(200, json={
                "id": f"resp_test_{index}", "object": "response", "created_at": 0, "status": "completed",
                "model": "gpt-4o-mini", "output": output,
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            })

        with OpenAI(api_key="test-only-not-a-real-key", http_client=httpx.Client(transport=httpx.MockTransport(http_handler))) as client:
            result = self.agent(OpenAIBackend(client=client)).chat("I'm Sam, sam@example.com. Please quote Jordan.")
        self.assertNotIn("error", result.trace)
        self.assertEqual(len(requests), 4)
        self.assertEqual(requests[0]["text"]["format"]["type"], "json_schema")
        self.assertTrue(requests[0]["text"]["format"]["strict"])
        self.assertTrue(requests[1]["tools"][0]["strict"])
        tool_output = requests[2]["input"][-1]
        self.assertEqual(tool_output["call_id"], "call_test")
        self.assertTrue(json.loads(tool_output["output"])["success"])
        self.assertEqual(len(self.db.records("leads")), 1)
        self.assertEqual(result.trace["usage"][0]["input_tokens"], 100)
        self.assertEqual(result.reply, outputs[-1]["final_reply"])


if __name__ == "__main__":
    unittest.main()
