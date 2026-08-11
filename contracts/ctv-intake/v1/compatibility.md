# CTV Intake Contract v1 compatibility

Producers and consumers must match major version `1`.

Consumers may accept added optional fields only after the contract tests pass.
Removing or renaming fields, changing enum meaning, or weakening coverage is a
major change.

Exception codes are append-only within v1.

WP records the exact CTV commit and tree digest in `SOURCE.json`.
