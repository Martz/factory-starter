import unittest
from decimal import Decimal

from lunchbox import Order, money


class MoneyTest(unittest.TestCase):
    def test_rounds_half_up_to_the_penny(self):
        self.assertEqual(money("2.345"), Decimal("2.35"))
        self.assertEqual(money(3), Decimal("3.00"))


class OrderTest(unittest.TestCase):
    def setUp(self):
        self.order = Order()
        self.order.add("Ada", "Falafel wrap", "7.50", ("vegan",))
        self.order.add("Grace", "Chicken katsu", "9.95")
        self.order.add("Ada", "Lemonade", "2.20", ("vegan", "gf"))

    def test_total_is_sum_of_items(self):
        self.assertEqual(self.order.total(), Decimal("19.65"))

    def test_each_person_pays_for_their_own_items(self):
        self.assertEqual(self.order.per_person(), {"Ada": Decimal("9.70"), "Grace": Decimal("9.95")})

    def test_tags_are_normalised(self):
        self.assertEqual(self.order.items[2].tags, frozenset({"vegan", "gf"}))

    def test_people_are_sorted(self):
        self.assertEqual(self.order.people(), ["Ada", "Grace"])


if __name__ == "__main__":
    unittest.main()
