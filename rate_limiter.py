import asyncio
from datetime import datetime, timedelta


lock = asyncio.Lock()

tokens_per_minute = []

async def rate_limiter(tokens_for_call: int):

    global tokens_per_minute

    req_per_minute = 10
    token_limit = 175_000

    while True:
        async with lock:
            cur_time = datetime.now()
            

            recent_requests = [
                req
                for req in tokens_per_minute
                if cur_time - req["datetime"] <= timedelta(seconds=60)
            ]
            
            tokens_per_minute = recent_requests # or tokens_per_minute[:] = recent_requests, to copy exact values across

            recent_token_count = sum(req["tokens"] for req in recent_requests)
            next_token_count = recent_token_count + tokens_for_call

            if len(recent_requests) < req_per_minute and next_token_count <= token_limit:
                tokens_per_minute.append({"datetime": cur_time, "tokens": tokens_for_call})
                return {"trim_tokens": False, "amount_to_trim": 0}

            if not recent_requests and tokens_for_call > token_limit:
                return {
                    "trim_tokens": True,
                    "amount_to_trim": tokens_for_call - token_limit + 1_000,
                }

        await asyncio.sleep(1)
