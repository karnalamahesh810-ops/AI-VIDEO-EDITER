import unittest

from src import config


class FlatSearches(unittest.TestCase):
    def test_flat_searches_ask_for_twenty_results(self):
        self.assertGreaterEqual(config.YT_SEARCH_RESULTS, 20)


if __name__ == "__main__":
    unittest.main()
