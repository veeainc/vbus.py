"""
    This example demonstrate how to expose an uri.
"""
import asyncio
import http.server
import socketserver
from http import HTTPStatus
from vbus import Client
import logging

logging.basicConfig(level=logging.DEBUG)

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(HTTPStatus.OK)
        self.end_headers()
        self.wfile.write(b'Hello world')


async def main():
    client = Client("system", "client_python")
    await client.connect()

    await client.expose("frontend", 'http', 21800)

    httpd = socketserver.TCPServer(('', 21800), Handler)
    httpd.serve_forever()

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
