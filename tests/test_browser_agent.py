from assistant.brain.agent_pipeline import AgentTask
from assistant.browser.controller import BrowserController


def test_browser_agent_result_contract_and_state():
    agent = BrowserController()
    assert agent.supports(AgentTask(action="open"))
    result = agent.execute(AgentTask(action="unknown"))
    assert (result.success, result.error) == (False, "unsupported_action")
    assert {"success", "message", "data", "error"} <= set(result.__dict__)
    assert {"active_tab", "current_url"} <= set(agent.state())


def test_play_result_opens_requested_normal_youtube_video(monkeypatch):
    agent = BrowserController()
    tab = agent._get_active_tab()
    assert tab is not None
    tab.domain = "youtube.com"
    tab.url = "https://www.youtube.com/results?search_query=jarvis"
    tab.last_query = "jarvis"
    tab.page_type = "search"

    response = type("Response", (), {
        "text": (
            '"reelItemRenderer":{"videoId":"short-video"}'
            '"videoRenderer":{"videoId":"normal-one"}'
            '"videoRenderer":{"videoId":"normal-two"}'
        ),
        "raise_for_status": lambda self: None,
    })()
    typed: list[str] = []
    monkeypatch.setattr("assistant.browser.controller.requests.get", lambda *args, **kwargs: response)
    monkeypatch.setattr("assistant.browser.controller.pyautogui.hotkey", lambda *keys: None)
    monkeypatch.setattr("assistant.browser.controller.pyautogui.write", lambda text, **kwargs: typed.append(text))
    monkeypatch.setattr("assistant.browser.controller.pyautogui.press", lambda key: None)

    result = agent.play_result(2)
    assert result.success
    assert typed == ["https://www.youtube.com/watch?v=normal-two"]
    assert agent.current_url == typed[0]
    assert "/results?" not in agent.current_url


def test_play_result_reports_missing_video(monkeypatch):
    agent = BrowserController()
    tab = agent._get_active_tab()
    assert tab is not None
    tab.domain, tab.url, tab.last_query = "youtube.com", "https://www.youtube.com/results?search_query=x", "x"
    response = type("Response", (), {"text": '"reelItemRenderer":{"videoId":"short"}', "raise_for_status": lambda self: None})()
    monkeypatch.setattr("assistant.browser.controller.requests.get", lambda *args, **kwargs: response)

    result = agent.play_result()
    assert not result.success and result.error == "result_not_found"


def test_youtube_search_and_play_reuse_the_active_tab(monkeypatch):
    agent = BrowserController()
    response = type("Response", (), {
        "text": '"videoRenderer":{"videoId":"first"}"videoRenderer":{"videoId":"second"}',
        "raise_for_status": lambda self: None,
    })()
    opened: list[str] = []
    typed: list[str] = []
    monkeypatch.setattr("assistant.browser.controller.webbrowser.open", lambda url: opened.append(url) or True)
    monkeypatch.setattr("assistant.browser.controller.requests.get", lambda *args, **kwargs: response)
    monkeypatch.setattr("assistant.browser.controller.pyautogui.hotkey", lambda *keys: None)
    monkeypatch.setattr("assistant.browser.controller.pyautogui.write", lambda text, **kwargs: typed.append(text))
    monkeypatch.setattr("assistant.browser.controller.pyautogui.press", lambda key: None)

    agent.open("youtube")
    agent.search("Avengers Endgame Trailer")
    result = agent.play_result(2)

    assert result.success
    assert len(agent.tabs) == 1
    assert opened == ["https://www.youtube.com"]
    assert typed == [
        "https://www.youtube.com/results?search_query=Avengers+Endgame+Trailer",
        "https://www.youtube.com/watch?v=second",
    ]
    assert agent.current_url == "https://www.youtube.com/watch?v=second"
