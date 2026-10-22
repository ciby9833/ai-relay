"""Emit promtool test cases using the actual application queries (JSON is YAML).

No database or model calls. Pipe output to a file and run `promtool test rules`.
"""
import json

from app.api.performance import COLLECTORS, QUERIES


def case(key, samples):
    return {"expr": QUERIES[key], "eval_time": "3m", "exp_samples": samples}


def sample(labels, value):
    return {"labels": labels, "value": value}


base = [
    {"series": 'up{job="node",instance="host"}', "values": "1+0x6"},
    {"series": 'up{job="cadvisor",instance="containers"}', "values": "1+0x6"},
    {"series": 'up{job="api",instance="api"}', "values": "1+0x6"},
    {"series": 'up{job="worker",instance="worker"}', "values": "0+0x6"},
    {"series": 'node_cpu_seconds_total{job="node",instance="host",mode="idle",cpu="0"}', "values": "0+15x6"},
    {"series": 'node_memory_MemAvailable_bytes{job="node",instance="host"}', "values": "400+0x6"},
    {"series": 'node_memory_MemTotal_bytes{job="node",instance="host"}', "values": "1000+0x6"},
    {"series": 'node_disk_read_bytes_total{job="node",instance="host",device="vda"}', "values": "0+300x6"},
    {"series": 'node_disk_read_bytes_total{job="node",instance="host",device="dm-0"}', "values": "0+300x6"},
    {"series": 'node_filesystem_avail_bytes{job="node",instance="host",device="vda1",mountpoint="/"}', "values": "0+0x6"},
    {"series": 'node_filesystem_device_error{job="node",instance="host",device="vda1",mountpoint="/"}', "values": "0+0x6"},
    {"series": 'container_cpu_usage_seconds_total{job="cadvisor",instance="containers",service="api",id="new"}', "values": "0+15x6"},
    {"series": 'container_cpu_usage_seconds_total{job="cadvisor",instance="containers",service="api",id="old"}', "values": "0+30x6"},
    {"series": 'container_last_seen{job="cadvisor",instance="containers",service="api",id="new"}', "values": "0+30x6"},
    {"series": 'container_last_seen{job="cadvisor",instance="containers",service="api",id="old"}', "values": "0+0x6"},
    {"series": 'relay_inflight{job="api",instance="api",kind="turn"}', "values": "2+0x6"},
    {"series": 'relay_inflight{job="worker",instance="worker",kind="turn"}', "values": "9+0x6"},
    {"series": 'relay_heartbeat_timestamp_seconds{job="api",instance="api"}', "values": "0+30x6"},
    {"series": 'relay_heartbeat_timestamp_seconds{job="worker",instance="worker"}', "values": "0+30x6"},
    {"series": 'relay_llm_seconds_count{provider="gemini",outcome="limited"}', "values": "0 0 0 1 1 1 1"},
    {"series": 'relay_llm_seconds_count{provider="openai",outcome="success"}', "values": "0 3 6 0 2 4 6"},
] + [{"series": f'node_scrape_collector_success{{job="node",collector="{collector}"}}', "values": "1+0x6"} for collector in COLLECTORS]


def changed(predicate, values):
    return [{**row, "values": values} if predicate(row["series"]) else dict(row) for row in base]


def fixtures():
    return {"rule_files": [], "evaluation_interval": "30s", "fuzzy_compare": True, "tests": [
        {"interval": "30s", "input_series": base, "promql_expr_test": [
            case("cpu", [sample("{}", 50)]),
            case("memory", [sample('{job="node",instance="host"}', 60)]),
            # Logical and physical disks remain distinct, rather than producing 20 B/s.
            case("disk_read", [sample(f'{{job="node",instance="host",device="{d}"}}', 10) for d in ("dm-0", "vda")]),
            case("disk_free", [sample('node_filesystem_avail_bytes{job="node",instance="host",device="vda1",mountpoint="/"}', 0)]),
            case("service_cpu", [sample('{service="api"}', .5)]),
            case("inflight", [sample('{kind="turn"}', 2)]),
            case("llm_calls", [sample('{provider="gemini",outcome="limited"}', 1), sample('{provider="openai",outcome="success"}', 12)]),
        ]},
        {"interval": "30s", "input_series": changed(lambda s: s.startswith('up{job="node"'), "1 _ _ _ _ _ _"),
         "promql_expr_test": [case("cpu", []), case("memory", [])]},
        {"interval": "30s", "input_series": changed(lambda s: s.startswith("node_filesystem_device_error"), "1+0x6"),
         "promql_expr_test": [case("disk_free", [])]},
        {"interval": "30s", "input_series": changed(lambda s: s.startswith("node_scrape_collector_success"), "0+0x6"),
         "promql_expr_test": [case("cpu", []), case("disk_read", []), case("disk_free", [])]},
        {"interval": "30s", "input_series": changed(lambda s: s.startswith("relay_heartbeat_timestamp_seconds"), "0+0x6"),
         "promql_expr_test": [case("inflight", [])]},
    ]}


if __name__ == "__main__":
    print(json.dumps(fixtures()))
