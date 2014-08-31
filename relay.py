import os
import json
import datetime
import tornado.web
import logging as log
import tornado.ioloop
import tornado.websocket
import tornado.httpserver


DESTINATIONS = set()
SOURCES = set()
MESSAGE_HISTORY = list()
TELEMETRY_PACKET = None


class TimeoutWebSocketHandler(tornado.websocket.WebSocketHandler):
    def __init__(self, *args, **kwargs):
        super(TimeoutWebSocketHandler, self).__init__(*args, **kwargs)
        self.timeout = None

    def _handle_timeout(self):
        if self.ws_connection:
            self.on_close()  # This isn't called by self.close
            self.close()

        self.timeout = None

    def reset_timeout(self):
        if self.timeout:
            tornado.ioloop.IOLoop.instance().remove_timeout(self.timeout)

        self.timeout = tornado.ioloop.IOLoop.instance().add_timeout(
            datetime.timedelta(milliseconds=30000), self._handle_timeout)


class RelayDestinationHandler(TimeoutWebSocketHandler):
    def open(self):
        global DESTINATIONS, MESSAGE_HISTORY

        log.info("RelayDestinationHandler.open()")

        DESTINATIONS.add(self)
        for msg in MESSAGE_HISTORY:
            self.write_message(msg)

    def on_message(self, message):
        global TELEMETRY_PACKET

        log.info(
            "RelayDestinationHandler.on_message({0})".format(repr(message)))

        self.reset_timeout()
        # If the message looks like a telemetry packet, keep track of it
        # to send to the relay sources
        if message[0] == "\x00" and message[-1] == "\x00":
            TELEMETRY_PACKET = message


    def on_close(self):
        global DESTINATIONS

        log.info("RelayDestinationHandler.close()")

        DESTINATIONS.remove(self)

    def check_origin(self, origin):
        return True


class RelaySourceHandler(TimeoutWebSocketHandler):
    def open(self):
        global SOURCES

        log.info("RelaySourceHandler.open()")

        SOURCES.add(self)

    def on_message(self, message):
        global MESSAGE_HISTORY, DESTINATIONS, TELEMETRY_PACKET

        log.info("RelaySourceHandler.on_message({0})".format(repr(message)))

        self.reset_timeout()
        # Relay the message to all connected destinations
        for dest in DESTINATIONS:
            dest.write_message(message)
        MESSAGE_HISTORY.append(message)

        # Acknowledge the message so the receiving end can determine it's
        # still connected
        self.write_message(TELEMETRY_PACKET or "ok")

    def on_close(self):
        global SOURCES

        log.info("RelaySourceHandler.close()")

        SOURCES.remove(self)

    def check_origin(self, origin):
        return True


class ImageHandler(tornado.web.RequestHandler):
    def get(self, *args, **kwargs):
        session = args[0]
        name = args[1]

        if not session.isalnum():
            raise tornado.web.HTTPError(400)

        if not name.startswith("img") and name not in ("all", "html"):
            raise tornado.web.HTTPError(400)

        if name == "all":
            msg = []
            for f in os.listdir("/tmp/uploads/"):
                s, _, n = f.partition("-")
                msg.append({"session": s, "name": n, "status": "done"})

            self.set_header("Content-Type", "application/json")

            self.finish(json.dumps(msg))
        elif name == "html":
            body = """<!doctype html5>
                <html>
                    <head>
                        <meta charset=utf-8>
                        <title>{0} images</title>
                    </head>
                    <body>
                        {1}
                    </body>
                </html>"""

            content = []
            for f in os.listdir("/tmp/uploads/"):
                s, _, n = f.partition("-")
                content.append("<img src=\"/vQivxdjcFcUH34mLAEcfm77varwTmAA8/{0}/{1}\" width=640 height=480>".format(s, n))

            self.set_header("Content-Type", "text/html")

            self.finish(body.format(len(content), "".join(content)))
        else:
            fname = os.path.join("/tmp/uploads", session + "-" + name)

            self.set_header("Content-Type", "image/jpeg")
            self.set_header("Date", datetime.datetime.utcnow())
            self.set_header("Vary", "Accept-Encoding")
            self.set_header("Cache-Control", "public, max-age=86400")

            with open(fname, "r") as f:
                self.finish(f.read())

    def post(self, *args, **kwargs):
        session = args[0]
        name = args[1]

        if not session.isalnum():
            raise tornado.web.HTTPError(400)

        if not name.startswith("img"):
            raise tornado.web.HTTPError(400)

        fname = os.path.join("/tmp/uploads", session + "-" + name)

        with open(fname, "wb") as f:
            f.write(self.request.body)

        for dest in DESTINATIONS:
            dest.write_message(json.dumps({"session": session, "name": name, "status": "done"}))


if __name__ == "__main__":
    log.getLogger().setLevel(log.DEBUG)
    app = tornado.web.Application([
            (r"/vQivxdjcFcUH34mLAEcfm77varwTmAA8/([a-zA-Z0-9]+)/(.+)", ImageHandler),
            (r"/P48WeGkwEFxheWVYEz6rGz4bbiwX4gkT", RelaySourceHandler),
            (r"/mwPhW4f8wKjUqH2fsWMDDiqk6z3meHGZ", RelayDestinationHandler),
        ],
        debug=True, gzip=True)
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(31285)
    tornado.ioloop.IOLoop.instance().start()
