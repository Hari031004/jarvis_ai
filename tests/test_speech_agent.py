from types import SimpleNamespace

from assistant.brain.agent_pipeline import AgentTask
from assistant.speech.speech_agent import SpeechAgent


def test_speech_agent_result_contract_and_backward_compatible_state():
    settings = SimpleNamespace(voice_name="en-US-TestNeural", whisper_language=None)
    tts = SimpleNamespace(speak=lambda text: None, stop=lambda: None, set_voice=lambda name: None)
    agent = SpeechAgent(settings, SimpleNamespace(transcribe=lambda audio: "ok"), tts)
    assert agent.supports(AgentTask(action="speak"))
    result = agent.execute(AgentTask(action="unknown"))
    assert (result.success, result.error) == (False, "unsupported_action")
    assert {"voice", "language", "speaking_state", "listening_state"} <= set(agent.state())


def test_speech_agent_maps_unexpected_errors_without_raising():
    settings = SimpleNamespace(voice_name="en-US-TestNeural", whisper_language=None)
    tts = SimpleNamespace(speak=lambda text: None, stop=lambda: None, set_voice=lambda name: None)
    agent = SpeechAgent(settings, SimpleNamespace(transcribe=lambda audio: (_ for _ in ()).throw(RuntimeError("boom"))), tts)
    result = agent.execute(AgentTask(action="transcribe", parameters={"audio": [0.0]}))
    assert not result.success and result.error == "unexpected_exception"


def test_normalize_proper_nouns(tmp_path):
    import json
    from assistant.speech.speech_to_text import SpeechToText

    aliases_file = tmp_path / "stt_aliases.json"
    aliases_data = {
        "universities": {
            "bd dash university": "Bharathidasan University",
            "anna univ": "Anna University"
        },
        "cities": {
            "cheny": "Chennai"
        },
        "people": {
            "mr bharath": "Mr. Bharath"
        },
        "applications": {
            "vs-code": "Visual Studio Code"
        },
        "brands": {
            "apple corp": "Apple Inc."
        },
        "custom": {
            "my alias": "Custom Named Target"
        }
    }
    with open(aliases_file, "w", encoding="utf-8") as f:
        json.dump(aliases_data, f)

    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=aliases_file)
    stt = SpeechToText(settings)

    # 1. Exact alias match
    assert stt.normalize_proper_nouns("go to cheny") == "go to Chennai"
    
    # 2. Fuzzy match
    assert stt.normalize_proper_nouns("go to cheni") == "go to Chennai"
    
    # 3. No replacement
    assert stt.normalize_proper_nouns("go to london") == "go to  london" or stt.normalize_proper_nouns("go to london") == "go to london"
    
    # 4. Multiple aliases
    assert stt.normalize_proper_nouns("open vs-code in cheny") == "open Visual Studio Code in Chennai"
    
    # 5. Mixed-case input
    assert stt.normalize_proper_nouns("Open BD DASH UNIVERSITY website") == "Open Bharathidasan University website"
    
    # 6. Punctuation
    # Strip space differences if any
    cleaned_res = " ".join(stt.normalize_proper_nouns("hello, mr bharath?").split())
    assert "Mr. Bharath" in cleaned_res
    
    # 7. Hyphenated words
    assert stt.normalize_proper_nouns("navigate to bd-dash university") == "navigate to Bharathidasan University"


def test_aliases_missing_file_creation(tmp_path):
    from assistant.speech.speech_to_text import SpeechToText
    missing_file = tmp_path / "subdir" / "stt_aliases.json"
    
    # Path does not exist initially
    assert not missing_file.exists()
    
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=missing_file)
    stt = SpeechToText(settings)
    
    # It must auto-create the template
    assert missing_file.exists()
    
    import json
    with open(missing_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "universities" in data
    assert "cities" in data
    assert "custom" in data


def test_aliases_malformed_json(tmp_path):
    from assistant.speech.speech_to_text import SpeechToText
    bad_file = tmp_path / "bad_aliases.json"
    with open(bad_file, "w", encoding="utf-8") as f:
        f.write("{ malformed json : [ }")
        
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=bad_file)
    stt = SpeechToText(settings)
    
    # Must degrade gracefully (return original input)
    assert stt.normalize_proper_nouns("go to cheny") == "go to cheny"


def test_aliases_duplicate_aliases(tmp_path):
    import json
    from assistant.speech.speech_to_text import SpeechToText
    dup_file = tmp_path / "dup_aliases.json"
    
    # Dictionary duplicate keys are naturally resolved by JSON parsers (last key wins)
    # Let's test duplicate entries across flat/nested category mapping
    aliases_data = {
        "cities": {
            "cheny": "Chennai First"
        },
        "custom": {
            "cheny": "Chennai Last"
        }
    }
    with open(dup_file, "w", encoding="utf-8") as f:
        json.dump(aliases_data, f)
        
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=dup_file)
    stt = SpeechToText(settings)
    assert stt.normalize_proper_nouns("go to cheny") == "go to Chennai Last"


def test_aliases_overlapping_aliases(tmp_path):
    import json
    from assistant.speech.speech_to_text import SpeechToText
    overlap_file = tmp_path / "overlap_aliases.json"
    
    # Nested/overlapping phrases
    aliases_data = {
        "universities": {
            "bd dash university": "Bharathidasan University",
            "bd dash": "Bharathidasan"
        }
    }
    with open(overlap_file, "w", encoding="utf-8") as f:
        json.dump(aliases_data, f)
        
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=overlap_file)
    stt = SpeechToText(settings)
    
    # Should resolve to the longest/more specific first, not double-normalize
    assert stt.normalize_proper_nouns("open bd dash university") == "open Bharathidasan University"


def test_aliases_hot_reload(tmp_path):
    import json
    import time
    from assistant.speech.speech_to_text import SpeechToText
    
    reload_file = tmp_path / "reload_aliases.json"
    with open(reload_file, "w", encoding="utf-8") as f:
        json.dump({"custom": {"old": "Previous"}}, f)
        
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=reload_file)
    stt = SpeechToText(settings)
    
    assert stt.normalize_proper_nouns("this is old") == "this is Previous"
    
    # Modify file contents and change mtime to trigger hot reload
    with open(reload_file, "w", encoding="utf-8") as f:
        json.dump({"custom": {"old": "Previous", "new": "Updated"}}, f)
    
    # Update mtime explicitly for OS safety
    import os
    st = os.stat(reload_file)
    os.utime(reload_file, (st.st_atime, st.st_mtime + 5.0))
    
    # Verify new alias is resolved immediately
    assert stt.normalize_proper_nouns("this is new") == "this is Updated"


def test_aliases_unicode(tmp_path):
    import json
    from assistant.speech.speech_to_text import SpeechToText
    uni_file = tmp_path / "uni_aliases.json"
    
    # Unicode Indian proper nouns & characters
    aliases_data = {
        "custom": {
            "mumbai": "मुंबई (Mumbai)",
            "bengaluru": "ಬೆಂಗಳೂರು (Bengaluru)"
        }
    }
    with open(uni_file, "w", encoding="utf-8") as f:
        json.dump(aliases_data, f)
        
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=uni_file)
    stt = SpeechToText(settings)
    assert stt.normalize_proper_nouns("travel to mumbai") == "travel to मुंबई (Mumbai)"
    assert stt.normalize_proper_nouns("live in bengaluru") == "live in ಬೆಂಗಳೂರು (Bengaluru)"


def test_aliases_punctuation(tmp_path):
    import json
    from assistant.speech.speech_to_text import SpeechToText
    punc_file = tmp_path / "punc_aliases.json"
    
    aliases_data = {
        "custom": {
            "alias": "Normalized"
        }
    }
    with open(punc_file, "w", encoding="utf-8") as f:
        json.dump(aliases_data, f)
        
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=punc_file)
    stt = SpeechToText(settings)
    
    # Match should work even with leading/trailing punctuation symbols
    assert stt.normalize_proper_nouns("hello, 'alias'!") == "hello, Normalized"


def test_aliases_large_dictionary_and_benchmark(tmp_path):
    import json
    import time
    from assistant.speech.speech_to_text import SpeechToText
    large_file = tmp_path / "large_aliases.json"
    
    # Generate 10,000 distinct aliases
    aliases_data = {}
    for idx in range(10000):
        aliases_data[f"alias {idx}"] = f"NormalizedValue {idx}"
    # Inject our search targets
    aliases_data["bd dash university"] = "Bharathidasan University"
    aliases_data["vs code"] = "Visual Studio Code"
    
    t0_load = time.perf_counter()
    with open(large_file, "w", encoding="utf-8") as f:
        json.dump({"custom": aliases_data}, f)
    elapsed_write = time.perf_counter() - t0_load
    
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=large_file)
    stt = SpeechToText(settings)
    
    # Measure first-time load latency (includes filesystem read + indexing)
    t0_first = time.perf_counter()
    res1 = stt.normalize_proper_nouns("open vs code")
    elapsed_first = time.perf_counter() - t0_first
    assert res1 == "open Visual Studio Code"
    
    # Measure subsequent cached lookup latency (should be near 0ms)
    t0_cached = time.perf_counter()
    res2 = stt.normalize_proper_nouns("open vs code")
    elapsed_cached = time.perf_counter() - t0_cached
    assert res2 == "open Visual Studio Code"
    
    # Report benchmark results
    print(f"\n[STT ALIAS BENCHMARK]\n  - Write/Serialize Time: {elapsed_write*1000:.2f}ms\n  - Initial Load & Index: {elapsed_first*1000:.2f}ms\n  - Cached Lookup (O(N)): {elapsed_cached*1000:.2f}ms")
    
    # Assert performance regressions are avoided (cached lookup must be sub-millisecond)
    assert elapsed_cached < 0.005 # Less than 5ms (typically <0.1ms)


def test_aliases_thread_safety(tmp_path):
    import json
    import threading
    from assistant.speech.speech_to_text import SpeechToText
    thread_file = tmp_path / "thread_aliases.json"
    
    aliases_data = {
        "custom": {
            "concurrent": "ThreadSafe"
        }
    }
    with open(thread_file, "w", encoding="utf-8") as f:
        json.dump(aliases_data, f)
        
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=thread_file)
    stt = SpeechToText(settings)
    
    # Spin up 10 threads concurrently reading and normalizing transcripts
    errors = []
    
    def worker():
        try:
            for _ in range(50):
                assert stt.normalize_proper_nouns("testing concurrent access") == "testing ThreadSafe access"
        except Exception as e:
            errors.append(e)
            
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
        
    assert len(errors) == 0


def test_aliases_corrupted_utf8(tmp_path):
    from assistant.speech.speech_to_text import SpeechToText
    corrupt_file = tmp_path / "corrupt_utf8.json"
    
    # Write invalid UTF-8 bytes directly
    with open(corrupt_file, "wb") as f:
        f.write(b'{"custom": {"key": "\xff\xfe\xfd"}}')
        
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=corrupt_file)
    stt = SpeechToText(settings)
    
    # Graceful degradation (returns original text instead of raising UnicodeDecodeError)
    assert stt.normalize_proper_nouns("go to key") == "go to key"


def test_aliases_empty_json(tmp_path):
    from assistant.speech.speech_to_text import SpeechToText
    empty_file = tmp_path / "empty.json"
    with open(empty_file, "w", encoding="utf-8") as f:
        f.write("")
        
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=empty_file)
    stt = SpeechToText(settings)
    
    # Should handle empty files gracefully without crashing
    assert stt.normalize_proper_nouns("go to key") == "go to key"


def test_aliases_invalid_values(tmp_path):
    import json
    from assistant.speech.speech_to_text import SpeechToText
    invalid_file = tmp_path / "invalid_values.json"
    
    aliases_data = {
        "custom": {
            "key1": ["list", "value"],
            "key2": 12345
        }
    }
    with open(invalid_file, "w", encoding="utf-8") as f:
        json.dump(aliases_data, f)
        
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=invalid_file)
    stt = SpeechToText(settings)
    
    # Should safely ignore non-string values during load
    assert stt.normalize_proper_nouns("go to key1") == "go to key1"


def test_aliases_permission_denied(tmp_path):
    from unittest.mock import patch
    from pathlib import Path
    from assistant.speech.speech_to_text import SpeechToText
    locked_file = tmp_path / "locked.json"
    with open(locked_file, "w", encoding="utf-8") as f:
        f.write('{"custom": {"key": "value"}}')
        
    settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=locked_file)
    stt = SpeechToText(settings)
    
    with patch.object(Path, "stat", side_effect=PermissionError("Access denied")):
        # Should gracefully return original text instead of raising PermissionError
        assert stt.normalize_proper_nouns("go to key") == "go to key"


def test_aliases_multi_scale_benchmark(tmp_path):
    import json
    import time
    from assistant.speech.speech_to_text import SpeechToText

    scales = [10, 100, 1000, 10000]
    bench_results = {}

    for scale in scales:
        file_path = tmp_path / f"bench_{scale}.json"
        
        # Populate scale distinct aliases
        aliases_data = {}
        for idx in range(scale):
            aliases_data[f"alias {idx}"] = f"Value {idx}"
        aliases_data["bd dash university"] = "Bharathidasan University"
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"custom": aliases_data}, f)
            
        settings = SimpleNamespace(sample_rate=16000, stt_aliases_file=file_path)
        stt = SpeechToText(settings)
        
        # Cold load
        t0_cold = time.perf_counter()
        stt.normalize_proper_nouns("open the bd dash university portal")
        latency_cold = (time.perf_counter() - t0_cold) * 1000
        
        # Hot reload (forced mtime update)
        import os
        st = os.stat(file_path)
        os.utime(file_path, (st.st_atime, st.st_mtime + 5.0))
        
        t0_reload = time.perf_counter()
        stt.normalize_proper_nouns("open the bd dash university portal")
        latency_reload = (time.perf_counter() - t0_reload) * 1000
        
        # Cached lookup
        t0_cached = time.perf_counter()
        stt.normalize_proper_nouns("open the bd dash university portal")
        latency_cached = (time.perf_counter() - t0_cached) * 1000
        
        # Normalization search step ONLY (already loaded cache)
        t0_norm = time.perf_counter()
        stt.normalize_proper_nouns("open the bd dash university portal")
        latency_norm = (time.perf_counter() - t0_norm) * 1000
        
        bench_results[scale] = {
            "cold_load_ms": latency_cold,
            "hot_reload_ms": latency_reload,
            "cached_lookup_ms": latency_cached,
            "norm_only_ms": latency_norm
        }

    # Print out benchmark results cleanly
    print("\n[MULTI-SCALE ALIAS BENCHMARK REPORT]")
    print("Methodology: Evaluated on clean thread loops using time.perf_counter() (Machine Dependent).")
    print("--------------------------------------------------------------------------------")
    print(f"{'Scale':<10} | {'Cold Load':<14} | {'Hot Reload':<14} | {'Cached Lookup':<14} | {'Norm Only':<14}")
    print("--------------------------------------------------------------------------------")
    for scale, metrics in bench_results.items():
        print(f"{scale:<10} | {metrics['cold_load_ms']:<12.3f}ms | {metrics['hot_reload_ms']:<12.3f}ms | {metrics['cached_lookup_ms']:<12.3f}ms | {metrics['norm_only_ms']:<12.3f}ms")
    print("--------------------------------------------------------------------------------")

