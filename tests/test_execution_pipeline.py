from types import SimpleNamespace

from assistant.brain.agent_pipeline import AgentTask, ExecutionEngine
from assistant.speech.speech_agent import SpeechAgent


def test_execution_engine_keeps_running_and_updates_speech_context():
    settings = SimpleNamespace(voice_name="en-US-TestNeural", whisper_language=None)
    tts = SimpleNamespace(speak=lambda text: None, stop=lambda: None, set_voice=lambda name: None)
    speech = SpeechAgent(settings, SimpleNamespace(transcribe=lambda audio: "ok"), tts)
    engine = ExecutionEngine(None, None, None, None, None, speech_agent=speech)
    response = engine.execute([AgentTask(agent="SpeechAgent", action="set_language", parameters={"language": "fr-FR"})])
    assert "changed" in response
    assert engine.context.language == "fr-FR"
    assert engine.context.voice == "en-US-TestNeural"


def test_execution_engine_does_not_raise_for_unsupported_agent():
    engine = ExecutionEngine(None, None, None, None, None)
    response = engine.execute([AgentTask(agent="UnknownAgent", action="unknown")])
    assert "Unsupported task agent" in response
