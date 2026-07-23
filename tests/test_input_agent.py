from types import SimpleNamespace

from assistant.brain.agent_pipeline import AgentTask
from assistant.desktop.input_agent import InputAgent


def test_input_agent_result_contract_and_state():
    agent = InputAgent(SimpleNamespace())
    assert agent.supports(AgentTask(action="press_key"))
    result = agent.execute(AgentTask(action="unknown"))
    assert (result.success, result.error) == (False, "unsupported_action")
    state = agent.state()
    assert {"last_mouse_position", "last_keyboard_action"} <= set(state)
