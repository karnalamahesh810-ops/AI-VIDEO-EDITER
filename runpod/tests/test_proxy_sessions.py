import importlib
import os
import unittest
from unittest import mock


class ProxySessions(unittest.TestCase):
    def test_template_expands_into_numbered_sticky_sessions(self):
        env = {"YTDLP_PROXY": "", "YTDLP_PROXY_TEMPLATE": "http://u-us-{n}:p@gw.example:80",
               "YTDLP_PROXY_SESSIONS": "3"}
        from src import config
        try:
            with mock.patch.dict(os.environ, env):
                importlib.reload(config)
                self.assertEqual(config.YTDLP_PROXIES, [
                    "http://u-us-1:p@gw.example:80", "http://u-us-2:p@gw.example:80",
                    "http://u-us-3:p@gw.example:80"])
        finally:
            importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
