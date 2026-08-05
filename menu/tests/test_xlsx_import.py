import io

import openpyxl
import pytest

from menu.pipeline import xlsx_import

HEAD = ['Category', 'Sub_Category', 'Item', 'Variant', 'Description',
        'Price', 'Image_Subject', 'Notes']


def book(rows, headers=HEAD, sheet_name='Menu'):
    """An in-memory .xlsx with `rows` under `headers`."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_reads_a_clean_row():
    result = xlsx_import.parse(book([
        ['Veg Snacks', '', 'French Fries', 'Plain', '', 250,
         'golden crispy french fries', ''],
    ]))
    assert result.errors == []
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.category == 'Veg Snacks'
    assert row.item == 'French Fries'
    assert row.variant == 'Plain'
    assert row.price == 250
    assert row.subject == 'golden crispy french fries'
    assert row.line == 2          # 1-based, header is line 1


def test_placeholder_dashes_read_as_empty_and_are_counted():
    result = xlsx_import.parse(book([
        ['Soup', '—', 'Veg Soup', '-', 'N/A', 120, 'a bowl of vegetable soup', 'none'],
    ]))
    assert result.errors == []
    row = result.rows[0]
    assert row.sub_category == ''
    assert row.variant == ''
    assert row.description == ''
    assert row.notes == ''
    assert result.dashes == 4


def test_price_must_be_a_whole_number():
    result = xlsx_import.parse(book([
        ['Soup', '', 'A', '', '', 'Rs 120', 'a bowl of soup', ''],
        ['Soup', '', 'B', '', '', 12.5, 'a bowl of soup', ''],
        ['Soup', '', 'C', '', '', '', 'a bowl of soup', ''],
    ]))
    messages = dict(result.errors)
    assert messages['Price is not a whole number'] == [2, 3]
    assert messages['Price is required'] == [4]
    assert result.rows == []


def test_errors_are_grouped_not_listed():
    rows = [['Soup', '', f'Item {i}', '', '', 'x', 'a bowl of soup', '']
            for i in range(12)]
    result = xlsx_import.parse(book(rows))
    assert len(result.errors) == 1
    message, lines = result.errors[0]
    assert message == 'Price is not a whole number'
    assert len(lines) == 12


def test_missing_required_cells_are_reported_per_column():
    result = xlsx_import.parse(book([
        ['', '', 'A', '', '', 100, 'a dish', ''],
        ['Soup', '', '', '', '', 100, 'a dish', ''],
        ['Soup', '', 'C', '', '', 100, '', ''],
    ]))
    messages = dict(result.errors)
    assert messages['Category is required'] == [2]
    assert messages['Item is required'] == [3]
    assert messages['Image_Subject is required'] == [4]


def test_wrong_headers_reject_the_file():
    result = xlsx_import.parse(book([], headers=['Category', 'Item', 'Price']))
    assert result.rows == []
    assert any('header' in m.lower() for m, _ in result.errors)


def test_a_sheet_with_no_data_rows_is_rejected():
    result = xlsx_import.parse(book([]))
    assert any('no data rows' in m.lower() for m, _ in result.errors)


def test_duplicate_rows_are_flagged_in_notes_not_rejected():
    result = xlsx_import.parse(book([
        ['Soup', '', 'Veg Soup', 'Plain', '', 120, 'a bowl of soup', ''],
        ['Soup', '', 'Veg Soup', 'Plain', '', 120, 'a bowl of soup', ''],
    ]))
    assert result.errors == []
    assert len(result.rows) == 2
    assert result.rows[0].notes == ''
    assert 'Duplicate of row 2' in result.rows[1].notes


def test_absurd_prices_are_flagged_in_notes():
    result = xlsx_import.parse(book([
        ['Soup', '', 'A', '', '', 0, 'a bowl of soup', ''],
        ['Soup', '', 'B', '', '', 250000, 'a bowl of soup', ''],
    ]))
    assert result.errors == []
    assert 'Price is 0' in result.rows[0].notes
    assert 'unusually high' in result.rows[1].notes.lower()


def test_falls_back_to_the_first_sheet_and_says_which():
    result = xlsx_import.parse(book([
        ['Soup', '', 'A', '', '', 120, 'a bowl of soup', ''],
    ], sheet_name='Sheet1'))
    assert result.errors == []
    assert result.sheet_name == 'Sheet1'


def test_line_numbers_survive_a_blank_row():
    result = xlsx_import.parse(book([
        ['Soup', '', 'A', '', '', 120, 'a bowl of soup', ''],   # line 2, clean
        ['', '', '', '', '', '', '', ''],                      # line 3, wholly blank
        ['Soup', '', 'B', '', '', 'bad', 'a bowl of soup', ''],  # line 4, faulty
    ]))
    messages = dict(result.errors)
    # The blank row at line 3 must not shift the fault on row B down to line 3;
    # it is the true worksheet row, line 4, regardless of how many blank rows
    # preceded it.
    assert messages['Price is not a whole number'] == [4]


def test_negative_price_in_a_numeric_cell_is_rejected():
    result = xlsx_import.parse(book([
        ['Soup', '', 'A', '', '', -50, 'a bowl of soup', ''],
    ]))
    messages = dict(result.errors)
    assert any('negative' in m.lower() for m in messages)
    assert [2] in messages.values()
    assert result.rows == []


def test_an_existing_note_is_preserved():
    result = xlsx_import.parse(book([
        ['Soup', '', 'A', '', '', 120, 'a bowl of soup', 'Price unclear (inferred)'],
    ]))
    assert result.rows[0].notes == 'Price unclear (inferred)'
