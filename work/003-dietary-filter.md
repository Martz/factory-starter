# Show only items with a dietary tag

The kitchen asks "which orders are vegan?" every week.

- The CLI accepts `--only TAG` (case-insensitive), which lists the matching items (person, item, price) instead of the bill.
- If nothing matches, print `no items tagged TAG` and exit 0.
