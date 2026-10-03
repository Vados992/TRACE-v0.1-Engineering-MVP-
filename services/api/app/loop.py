import asyncio


def selector_loop():
    # psycopg async connections require a selector loop on Windows.
    return asyncio.SelectorEventLoop()
