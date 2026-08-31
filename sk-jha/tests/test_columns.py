from phantom.columns import COLUMN_KEYS, COLUMNS, empty_row


def test_column_keys_are_unique():
    assert len(set(COLUMN_KEYS)) == len(COLUMN_KEYS)


def test_empty_row_covers_every_column():
    row = empty_row()
    assert set(row) == set(COLUMN_KEYS)
    assert all(value is None for value in row.values())


def test_labels_are_unique_and_non_empty():
    labels = [column.label for column in COLUMNS]
    assert all(labels)
    assert len(set(labels)) == len(labels)
