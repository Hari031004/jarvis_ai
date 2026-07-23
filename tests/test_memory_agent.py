from assistant.brain.agent_pipeline import AgentTask
from assistant.config import Settings
from assistant.memory.conversation import ConversationMemory


def test_memory_agent_result_contract_and_state(tmp_path):
    settings = Settings(database_path=tmp_path / "memory.db", data_dir=tmp_path, rag_vector_dimensions=8)
    agent = ConversationMemory(settings)
    assert agent.supports(AgentTask(action="store"))
    result = agent.execute(AgentTask(action="unknown"))
    assert (result.success, result.error) == (False, "unsupported_action")
    assert {"active_session", "last_memory"} <= set(agent.state())
