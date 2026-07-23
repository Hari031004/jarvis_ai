from types import SimpleNamespace

from assistant.brain.agent_pipeline import AgentTask
from assistant.desktop.application import ApplicationController


def test_desktop_agent_result_contract_and_state():
    agent = ApplicationController(SimpleNamespace())
    assert agent.supports(AgentTask(action="open_application"))
    result = agent.execute(AgentTask(action="unknown"))
    assert (result.success, result.error) == (False, "unsupported_action")
    assert {"active_application", "active_window"} <= set(agent.state())
