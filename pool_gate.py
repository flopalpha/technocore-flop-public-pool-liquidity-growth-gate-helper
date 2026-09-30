"""FLOP Public Pool Liquidity-Growth Gate Helper.

Read-only screening for public pool snapshots.
No keys, no wallets, no network, no trading.
"""

import csv
import hashlib
import json
from pathlib import Path

DEFAULT_WINDOW_MINUTES = 15
DEFAULT_MIN_LIQUIDITY = 1000.0
DEFAULT_MIN_DELTA = 100.0
DEFAULT_PASS_SCORE = 60.0
DEFAULT_REVIEW_SCORE = 40.0
DEFAULT_TOP_N = 5


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def normalize_snapshot(raw):
    try:
        pool_id = str(raw.get("pool_id", "")).strip()
        if not pool_id:
            return None
        ts = int(float(raw.get("timestamp", "")))
        liq = float(raw.get("liquidity", ""))
        price = float(raw.get("price", ""))
    except (TypeError, ValueError, AttributeError):
        return None
    if ts < 0:
        return None
    if liq < 0 or price < 0:
        return None
    return {
        "pool_id": pool_id,
        "timestamp": ts,
        "liquidity": liq,
        "price": price,
    }


def load_csv_snapshots(path):
    snapshots = []
    p = Path(path)
    with p.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
        for row in reader:
            lowered = {}
            for k, v in row.items():
                if k is None:
                    continue
                lowered[k.strip().lower()] = v
            raw = {
                "pool_id": lowered.get("pool_id", ""),
                "timestamp": lowered.get("timestamp", ""),
                "liquidity": lowered.get("liquidity", ""),
                "price": lowered.get("price", ""),
            }
            item = normalize_snapshot(raw)
            if item is not None:
                snapshots.append(item)
    return snapshots


def load_json_snapshots(path):
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "snapshots" in data:
        data = data["snapshots"]
    if not isinstance(data, list):
        raise ValueError("JSON must be a list of snapshots")
    snapshots = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        mapped = {
            "pool_id": raw.get("pool_id", raw.get("pool", raw.get("id", ""))),
            "timestamp": raw.get("timestamp", raw.get("ts", "")),
            "liquidity": raw.get("liquidity", raw.get("liq", "")),
            "price": raw.get("price", ""),
        }
        item = normalize_snapshot(mapped)
        if item is not None:
            snapshots.append(item)
    return snapshots


def load_snapshots(path):
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return load_csv_snapshots(path)
    if suffix == ".json":
        return load_json_snapshots(path)
    raise ValueError("unsupported file type, use .csv or .json")


def floor_bucket(ts, window_seconds):
    return (ts // window_seconds) * window_seconds


def bucket_snapshots(snapshots, window_minutes=15):
    window_seconds = int(window_minutes * 60)
    if window_seconds <= 0:
        raise ValueError("window_minutes must be positive")
    buckets = {}
    for s in snapshots:
        key = floor_bucket(s["timestamp"], window_seconds)
        buckets.setdefault(key, []).append(s)
    return buckets


def summarize_pools(snapshots):
    summary = {}
    for s in snapshots:
        pid = s["pool_id"]
        if pid not in summary:
            summary[pid] = {
                "pool_id": pid,
                "count": 0,
                "first_seen": s["timestamp"],
                "last_seen": s["timestamp"],
                "first_liquidity": s["liquidity"],
                "last_liquidity": s["liquidity"],
                "max_liquidity": s["liquidity"],
                "min_liquidity": s["liquidity"],
            }
        e = summary[pid]
        e["count"] += 1
        if s["timestamp"] < e["first_seen"]:
            e["first_seen"] = s["timestamp"]
            e["first_liquidity"] = s["liquidity"]
        if s["timestamp"] > e["last_seen"]:
            e["last_seen"] = s["timestamp"]
            e["last_liquidity"] = s["liquidity"]
        if s["liquidity"] > e["max_liquidity"]:
            e["max_liquidity"] = s["liquidity"]
        if s["liquidity"] < e["min_liquidity"]:
            e["min_liquidity"] = s["liquidity"]
    for e in summary.values():
        e["delta"] = e["last_liquidity"] - e["first_liquidity"]
    return summary


def earliest_first_ranking(snapshots):
    summary = summarize_pools(snapshots)
    ordered = sorted(summary.values(), key=lambda e: (e["first_seen"], e["pool_id"]))
    return [e["pool_id"] for e in ordered]


def liquidity_weighted_ranking(snapshots):
    summary = summarize_pools(snapshots)
    ordered = sorted(summary.values(), key=lambda e: (-e["max_liquidity"], e["pool_id"]))
    return [e["pool_id"] for e in ordered]


def compare_rankings(snapshots, window_minutes=15, top_n=5, min_liquidity=1000.0):
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    buckets = bucket_snapshots(snapshots, window_minutes)
    summary = summarize_pools(snapshots)
    earliest = earliest_first_ranking(snapshots)
    weighted = liquidity_weighted_ranking(snapshots)
    earliest_top = earliest[:top_n]
    weighted_top = weighted[:top_n]
    overlap = [p for p in earliest_top if p in weighted_top]
    dust_in_earliest = 0
    for pid in earliest_top:
        info = summary.get(pid)
        if info is not None and info["max_liquidity"] < min_liquidity:
            dust_in_earliest += 1
    note = "earliest-first matches liquidity-weighted"
    if dust_in_earliest > 0:
        note = "earliest-first top includes low-liquidity pools; prefer liquidity-weighted"
    if len(overlap) == 0 and len(earliest_top) > 0:
        note = "no overlap between earliest and liquidity ranking; dust bias likely"
    return {
        "window_minutes": window_minutes,
        "bucket_count": len(buckets),
        "earliest_top": earliest_top,
        "weighted_top": weighted_top,
        "overlap": overlap,
        "overlap_count": len(overlap),
        "dust_in_earliest_top": dust_in_earliest,
        "note": note,
    }


def flag_dust_pools(summaries, min_liquidity=1000.0, min_delta=100.0):
    flags = {}
    for pid, info in summaries.items():
        max_liq = info["max_liquidity"]
        delta = info["delta"]
        reasons = []
        is_dust = False
        if max_liq < min_liquidity:
            is_dust = True
            reasons.append("max liquidity below minimum")
        if delta < min_delta:
            is_dust = True
            reasons.append("liquidity delta below minimum")
        if not is_dust:
            reasons.append("passes dust thresholds")
        flags[pid] = {
            "pool_id": pid,
            "is_dust": is_dust,
            "max_liquidity": max_liq,
            "delta": delta,
            "reasons": reasons,
        }
    return flags


def group_by_pool(snapshots):
    grouped = {}
    for s in snapshots:
        grouped.setdefault(s["pool_id"], []).append(s)
    for pid in grouped:
        grouped[pid] = sorted(grouped[pid], key=lambda x: x["timestamp"])
    return grouped


def pearson(xs, ys):
    n = len(xs)
    if n != len(ys) or n < 2:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = 0.0
    den_x = 0.0
    den_y = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        dy = y - mean_y
        num += dx * dy
        den_x += dx * dx
        den_y += dy * dy
    den = (den_x * den_y) ** 0.5
    if den == 0.0:
        return 0.0
    return clamp(num / den, -1.0, 1.0)


def score_pool(points):
    if not points:
        return {
            "liq_change": 0.0,
            "liq_change_pct": 0.0,
            "price_change_pct": 0.0,
            "correlation": 0.0,
            "score": 0.0,
            "reasons": ["no points"],
        }
    ordered = sorted(points, key=lambda p: p["timestamp"])
    first_liq = ordered[0]["liquidity"]
    last_liq = ordered[-1]["liquidity"]
    first_price = ordered[0]["price"]
    last_price = ordered[-1]["price"]
    liqs = [p["liquidity"] for p in ordered]
    prices = [p["price"] for p in ordered]
    corr = pearson(liqs, prices)
    if first_liq > 0:
        liq_pct = (last_liq - first_liq) / first_liq * 100.0
    else:
        if last_liq > 0:
            liq_pct = 100.0
        else:
            liq_pct = 0.0
    if first_price > 0:
        price_pct = (last_price - first_price) / first_price * 100.0
    else:
        if last_price > 0:
            price_pct = 100.0
        else:
            price_pct = 0.0
    liq_c = clamp(liq_pct / 100.0, -1.0, 1.0)
    price_c = clamp(price_pct / 100.0, -1.0, 1.0)
    avg = (liq_c + price_c + corr) / 3.0
    score = round((avg + 1.0) * 50.0, 2)
    reasons = []
    if liq_pct > 0 and price_pct > 0 and corr > 0.2:
        reasons.append("liquidity and price grew together")
    if liq_pct <= 0:
        reasons.append("liquidity did not grow")
    if price_pct <= 0:
        reasons.append("price did not grow")
    if corr <= 0.2 and corr > -0.2:
        reasons.append("weak liquidity-price link")
    if corr <= -0.2:
        reasons.append("liquidity and price moved apart")
    if liq_pct > 0 and price_pct > 0 and corr <= 0.2:
        reasons.append("growth without clear link")
    if not reasons:
        reasons.append("mixed signal")
    return {
        "liq_change": round(last_liq - first_liq, 2),
        "liq_change_pct": round(liq_pct, 2),
        "price_change_pct": round(price_pct, 2),
        "correlation": round(corr, 4),
        "score": score,
        "reasons": reasons,
    }


def decide_gate(is_dust, score, liq_change, correlation, pass_score=60.0, review_score=40.0):
    if is_dust:
        return ("FAIL", "dust or flat pool")
    if score >= pass_score and liq_change > 0 and correlation > 0.2:
        return ("PASS", "growth gate passed")
    if score >= review_score and liq_change > 0:
        return ("REVIEW", "partial growth signal")
    return ("FAIL", "growth gate not met")


def rank_pools(snapshots, min_liquidity=1000.0, min_delta=100.0, pass_score=60.0, review_score=40.0):
    summaries = summarize_pools(snapshots)
    flags = flag_dust_pools(summaries, min_liquidity, min_delta)
    grouped = group_by_pool(snapshots)
    results = []
    for pid, points in grouped.items():
        scored = score_pool(points)
        flag = flags.get(pid)
        if flag is None:
            is_dust = False
            dust_reasons = []
        else:
            is_dust = flag["is_dust"]
            dust_reasons = flag["reasons"]
        gate, gate_reason = decide_gate(is_dust, scored["score"], scored["liq_change"], scored["correlation"], pass_score, review_score)
        all_reasons = []
        all_reasons.extend(dust_reasons)
        all_reasons.extend(scored["reasons"])
        all_reasons.append(gate_reason)
        results.append({
            "pool_id": pid,
            "score": scored["score"],
            "liq_change": scored["liq_change"],
            "liq_change_pct": scored["liq_change_pct"],
            "price_change_pct": scored["price_change_pct"],
            "correlation": scored["correlation"],
            "max_liquidity": summaries[pid]["max_liquidity"],
            "delta": summaries[pid]["delta"],
            "is_dust": is_dust,
            "gate": gate,
            "reasons": all_reasons,
        })
    results.sort(key=lambda r: (-r["score"], r["pool_id"]))
    return results


def compute_checksum(snapshots):
    ordered = sorted(snapshots, key=lambda s: (s["pool_id"], s["timestamp"]))
    text = json.dumps(ordered, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_report(snapshots, window_minutes=15, min_liquidity=1000.0, min_delta=100.0, pass_score=60.0, review_score=40.0, top_n=5):
    summaries = summarize_pools(snapshots)
    comparison = compare_rankings(snapshots, window_minutes, top_n, min_liquidity)
    ranked = rank_pools(snapshots, min_liquidity, min_delta, pass_score, review_score)
    params = {
        "window_minutes": window_minutes,
        "min_liquidity": min_liquidity,
        "min_delta": min_delta,
        "pass_score": pass_score,
        "review_score": review_score,
        "top_n": top_n,
    }
    return {
        "checksum": compute_checksum(snapshots),
        "params": params,
        "snapshot_count": len(snapshots),
        "pool_count": len(summaries),
        "bucket_comparison": comparison,
        "pools": ranked,
    }


def write_json_report(report, path):
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    return str(p)


def write_markdown_report(report, path):
    lines = []
    lines.append("# FLOP Pool Liquidity-Growth Gate Report")
    lines.append("")
    lines.append("Observational screening only. Not financial advice.")
    lines.append("")
    lines.append("Checksum: " + str(report.get("checksum", "")))
    lines.append("")
    params = report.get("params", {})
    lines.append("## Parameters")
    lines.append("")
    for key in ["window_minutes", "min_liquidity", "min_delta", "pass_score", "review_score", "top_n"]:
        lines.append("- " + key + ": " + str(params.get(key, "")))
    lines.append("")
    lines.append("Snapshots: " + str(report.get("snapshot_count", 0)))
    lines.append("")
    lines.append("Pools: " + str(report.get("pool_count", 0)))
    lines.append("")
    comp = report.get("bucket_comparison", {})
    lines.append("## Bucket Comparison")
    lines.append("")
    lines.append("Note: " + str(comp.get("note", "")))
    lines.append("")
    lines.append("Earliest top: " + ", ".join(comp.get("earliest_top", [])))
    lines.append("")
    lines.append("Weighted top: " + ", ".join(comp.get("weighted_top", [])))
    lines.append("")
    lines.append("Overlap: " + str(comp.get("overlap_count", 0)))
    lines.append("")
    lines.append("Dust in earliest top: " + str(comp.get("dust_in_earliest_top", 0)))
    lines.append("")
    lines.append("## Ranked Pools")
    lines.append("")
    lines.append("| rank | pool | score | liq change | price pct | corr | gate | reasons |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    pools = report.get("pools", [])
    rank = 1
    for item in pools:
        reasons = "; ".join(item.get("reasons", []))
        reasons = reasons.replace("|", "/")
        row = "| " + str(rank) + " | " + str(item.get("pool_id", "")) + " | " + str(item.get("score", "")) + " | " + str(item.get("liq_change", "")) + " | " + str(item.get("price_change_pct", "")) + " | " + str(item.get("correlation", "")) + " | " + str(item.get("gate", "")) + " | " + reasons + " |"
        lines.append(row)
        rank += 1
    lines.append("")
    text = "\n".join(lines)
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        f.write(text)
    return str(p)
