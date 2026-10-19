import tempfile
import unittest
from pathlib import Path

from lunchbox.cli import load, render

CSV = """person,item,price,tags
Ada,Falafel wrap,7.50,vegan
Grace,Chicken katsu,9.95,
Ada,Lemonade,2.20,vegan;gf
"""


class CliTest(unittest.TestCase):
    def test_render_shows_each_person_and_total(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "order.csv"
            path.write_text(CSV)
            out = render(load(path))
        self.assertIn("Ada", out)
        self.assertIn("9.70", out)
        self.assertIn("TOTAL", out)
        self.assertTrue(out.strip().endswith("19.65"))


if __name__ == "__main__":
    unittest.main()
