from types import SimpleNamespace

from assistant.brain.agent_pipeline import AgentTask
from assistant.vision.service import VisionService


def test_vision_agent_result_contract_and_state(tmp_path):
    agent = VisionService(SimpleNamespace(vision_output_dir=tmp_path, webcam_index=0))
    assert agent.supports(AgentTask(action="analyze"))
    result = agent.execute(AgentTask(action="unknown"))
    assert (result.success, result.error) == (False, "unsupported_action")
    assert {"success", "message", "data", "error"} <= set(result.__dict__)
    assert "latest_observation" in agent.state()
