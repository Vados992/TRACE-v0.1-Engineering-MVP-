"""Small repeatable latency/concurrency gate for the production-like API."""

import argparse
import asyncio
import statistics
import time

import httpx


async def run(base_url: str, requests: int, concurrency: int, p95_limit_ms: float):
    semaphore = asyncio.Semaphore(concurrency)
    latencies = []
    failures = []

    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        for _ in range(5):
            response = await client.get("/api/public/releases")
            response.raise_for_status()

        async def one(index: int):
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get("/api/public/releases")
                    if response.status_code != 200:
                        failures.append((index, response.status_code))
                except Exception as exc:
                    failures.append((index, type(exc).__name__))
                finally:
                    latencies.append((time.perf_counter() - started) * 1000)

        await asyncio.gather(*(one(i) for i in range(requests)))

    if failures:
        raise SystemExit(f"performance smoke request failures: {failures[:5]}")
    ordered = sorted(latencies)
    p50 = statistics.median(ordered)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    p99 = ordered[max(0, int(len(ordered) * 0.99) - 1)]
    print(
        f"performance smoke: requests={requests} concurrency={concurrency} "
        f"p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms"
    )
    if p95 > p95_limit_ms:
        raise SystemExit(
            f"performance smoke p95 {p95:.1f}ms exceeds configured {p95_limit_ms:.1f}ms"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--p95-ms", type=float, default=1500)
    args = parser.parse_args()
    if args.requests < 1 or args.requests > 10000:
        raise SystemExit("requests must be between 1 and 10000")
    if args.concurrency < 1 or args.concurrency > 200:
        raise SystemExit("concurrency must be between 1 and 200")
    asyncio.run(run(args.base_url, args.requests, args.concurrency, args.p95_ms))


if __name__ == "__main__":
    main()
