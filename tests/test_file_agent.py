from types import SimpleNamespace

from assistant.brain.agent_pipeline import AgentTask
from assistant.desktop.file_agent import FileAgent


def test_file_agent_result_contract_state_and_permission_error(tmp_path):
    agent = FileAgent(SimpleNamespace(user_workspace_dir=tmp_path))
    assert agent.supports(AgentTask(action="create_file"))
    created = agent.execute(AgentTask(action="create_file", parameters={"path": "a.txt", "content": "ok"}))
    assert created.success and {"current_file", "current_directory"} <= set(created.data)
    unsupported = agent.execute(AgentTask(action="unknown"))
    assert unsupported.error == "unsupported_action"
