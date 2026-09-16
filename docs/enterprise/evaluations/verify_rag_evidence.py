"""离线复核保存的合成检索证据；不访问网络，不等于重新执行容器测试。"""

import hashlib
import json
from pathlib import Path
import statistics
import sys


def verify(path: Path) -> None:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    total_bytes = 0
    for fixture in evidence["fixtures"].values():
        data = fixture["text"].encode("utf-8")
        assert len(data) == fixture["bytes"], "语料字节数不一致"
        assert hashlib.sha256(data).hexdigest() == fixture["sha256"], "语料 hash 不一致"
        total_bytes += len(data)
    assert total_bytes == 1015, "测试语料发生变化"

    contexts = evidence["observed_contexts_by_sha256"]
    for digest, content in contexts.items():
        assert hashlib.sha256(content.encode("utf-8")).hexdigest() == digest, "context hash 不一致"
    for provider in ("lightrag", "weknora"):
        result = evidence[provider]
        assert len(result["queries"]) == 5, "查询数不一致"
        for query in result["queries"]:
            content = query["join_separator"].join(contexts[key] for key in query["context_sha256"])
            hit = all(expected in content for expected in query["expected_substrings"])
            foreign = query["forbidden_substring"] in content
            assert hit == query["expected_in_context"], "预期字符串匹配记录不一致"
            assert foreign == query["foreign_canary_present"], "跨范围识别串记录不一致"
            assert hit and not foreign, "不再满足本轮五问的弱匹配结论"
        median = statistics.median(query["seconds"] for query in result["queries"])
        assert median == result["latency_median_seconds"], "延迟中位数不一致"

    graph = evidence["lightrag"]["graph_query"]
    assert {key: len(value) for key, value in graph["observed_data"].items()} == graph["counts"]
    print("证据离线一致性通过：语料/context hash、五问匹配、中位耗时、图结果计数。")
    print("这不是模型事实正确性、HTTP/容器复跑或生产门禁验收。")


if __name__ == "__main__":
    default_path = Path(__file__).with_name("2026-09-13-rag-services-results.json")
    verify(Path(sys.argv[1]) if len(sys.argv) > 1 else default_path)
