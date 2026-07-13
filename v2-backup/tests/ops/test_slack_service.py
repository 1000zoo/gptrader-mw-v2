import asyncio

from src.ops.service.slack.slack_service import SlackService


def test_send_message():
    async def inner():
        service = SlackService()
        await service.send_message("test", "HELLO!!")

    asyncio.run(inner())