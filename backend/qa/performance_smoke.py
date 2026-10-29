#!/usr/bin/env python3
"""Small authenticated, read-only API performance smoke test for a local demo."""

import argparse
import concurrent.futures
import getpass
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request


def request_json(url, payload=None, token=None, timeout=15):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--path", default="/api/farmers/", help="Read-only GET endpoint")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--max-p95-ms", type=float, default=None, help="Optional locally agreed response-time limit")
    args = parser.parse_args()

    if args.requests < 1 or args.workers < 1:
        parser.error("--requests and --workers must both be positive")

    base_url = args.base_url.rstrip("/")
    login_url = f"{base_url}/api/auth/login/"
    endpoint = urllib.parse.urljoin(f"{base_url}/", args.path.lstrip("/"))
    email = input("Operator email: ").strip()
    password = getpass.getpass("Operator password (hidden): ")
    status, body = request_json(login_url, {"email": email, "password": password})
    if status != 200:
        raise SystemExit(f"Login failed with HTTP {status}; no performance requests were sent.")
    access_token = json.loads(body).get("access")
    if not access_token:
        raise SystemExit("Login response contained no access token; no performance requests were sent.")

    def sample(_):
        started = time.perf_counter()
        try:
            status_code, _body = request_json(endpoint, token=access_token)
            return (time.perf_counter() - started) * 1000, status_code, None
        except Exception as error:  # Report transport failures as failed samples.
            return (time.perf_counter() - started) * 1000, None, str(error)

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        samples = list(pool.map(sample, range(args.requests)))
    elapsed = time.perf_counter() - started

    latencies = [sample[0] for sample in samples]
    successful = sum(1 for _, status_code, error in samples if status_code and 200 <= status_code < 300 and not error)
    failed = len(samples) - successful
    p95_ms = percentile(latencies, 0.95)
    print(f"GET {endpoint}")
    print(f"Requests: {len(samples)} | workers: {args.workers} | elapsed: {elapsed:.2f}s")
    print(f"Successes: {successful} | failures: {failed} | throughput: {len(samples) / elapsed:.2f} req/s")
    print(f"Latency ms: min={min(latencies):.2f} median={statistics.median(latencies):.2f} p95={p95_ms:.2f} max={max(latencies):.2f}")
    for _, status_code, error in samples:
        if error:
            print(f"Transport error: {error}")
        elif status_code is not None and not 200 <= status_code < 300:
            print(f"HTTP response: {status_code}")

    if failed:
        raise SystemExit(1)
    if args.max_p95_ms is not None and p95_ms > args.max_p95_ms:
        raise SystemExit(f"p95 exceeded the supplied threshold ({args.max_p95_ms:.2f} ms).")


if __name__ == "__main__":
    main()
