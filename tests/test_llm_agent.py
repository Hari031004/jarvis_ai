from assistant.brain.agent_pipeline import AgentTask
from assistant.agents.llm import LLMClient


def test_llm_agent_result_contract_and_state_without_provider_setup():
    agent = LLMClient.__new__(LLMClient)
    agent.active_model = "test-model"
    agent.provider = "test-provider"
    agent.last_prompt = ""
    agent.last_response = ""
    agent.token_usage = 0
    agent.request_count = 0
    assert agent.supports(AgentTask(action="generate"))
    result = agent.execute(AgentTask(action="unknown"))
    assert (result.success, result.error) == (False, "unsupported_action")
    assert {"provider", "model", "token_usage"} <= set(agent.state())
