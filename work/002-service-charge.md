# Add an optional service charge

The restaurant adds 12.5% service. We need to share it fairly.

- An order can have an optional service charge percentage (default 0).
- `total()` includes the service charge, rounded to the penny.
- `per_person()` shares the service charge in proportion to what each person ordered.
- The CLI accepts `--service 12.5`.
