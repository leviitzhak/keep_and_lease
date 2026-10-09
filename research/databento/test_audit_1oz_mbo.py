from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from audit_1oz_mbo import Book


class ReconstructionTests(unittest.TestCase):
    def book(self):
        book = Book()
        book.apply('R', 'N', 0, 0, 0)
        book.apply('A', 'B', 1, 100, 5)
        book.apply('A', 'A', 2, 110, 7)
        self.assertEqual(book.condition(), 'two_sided')
        return book

    def test_partial_cancel_preserves_remaining_quantity(self):
        book = self.book()
        book.apply('C', 'B', 1, 100, 2)
        self.assertEqual(book.orders[1], ('B', 100, 3))
        self.assertEqual(book.condition(), 'two_sided')
        book.apply('C', 'B', 1, 100, 3)
        self.assertNotIn(1, book.orders)
        self.assertEqual(book.condition(), 'one_sided_or_empty')

    def test_trade_and_fill_do_not_double_subtract(self):
        book = self.book()
        for action in ('T', 'F', 'N'):
            book.apply(action, 'B', 1, 100, 2)
        self.assertEqual(book.orders[1][2], 5)

    def test_modify_moves_price_and_replaces_size(self):
        book = self.book()
        book.apply('M', 'A', 2, 120, 3)
        self.assertEqual(book.orders[2], ('A', 120, 3))
        self.assertEqual(book.condition(), 'two_sided')
        book.apply('M', 'A', 2, 100, 3)
        self.assertEqual(book.condition(), 'locked_or_crossed')

    def test_unknown_cancel_invalidates_until_reset(self):
        book = self.book()
        book.apply('C', 'B', 999, 100, 1)
        self.assertEqual(book.condition(), 'uninitialized')
        self.assertEqual(book.errors['unknown_C'], 1)
        book.apply('R', 'N', 0, 0, 0)
        self.assertEqual(book.condition(), 'one_sided_or_empty')
        self.assertEqual(book.orders, {})

    def test_oversize_cancel_is_not_silently_accepted(self):
        book = self.book()
        book.apply('C', 'B', 1, 100, 6)
        self.assertEqual(book.errors['cancel_exceeds_size'], 1)
        self.assertEqual(book.condition(), 'uninitialized')


if __name__ == '__main__':
    unittest.main()
