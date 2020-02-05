import os
import asyncio
import natsplayer


def setup_test(scenario: str) -> natsplayer.Player:
    conf_file = os.path.expanduser("~/vbus/test.vbuspy.conf")
    if os.path.exists(conf_file):
        os.remove(conf_file)
    player = natsplayer.Player("test.vbuspy")
    player.play(scenario)
    return player


def async_test(f):
    def wrapper(*args, **kwargs):
        coro = asyncio.coroutine(f)
        future = coro(*args, **kwargs)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(future)

    return wrapper
