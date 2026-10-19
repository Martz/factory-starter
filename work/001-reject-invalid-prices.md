# Reject invalid prices

Someone typed `-4.50` for a coffee last Friday and the bill went *down*.

- Adding an item whose price is zero, negative or not a number should raise `ValueError` with a message that names the person and the item.
- The CLI should not show a stack trace for a bad row. It should print `error: line N: <message>` to stderr and exit with status 2 (N is the line number in the CSV file; the header is line 1).
