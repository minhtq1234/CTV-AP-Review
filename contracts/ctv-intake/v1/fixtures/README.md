# Synthetic CTV intake fixtures

These fixtures are contract examples only. They use fake identifiers such as
`FA-SYNTH-001` and contain no customer inputs or personal data.

`complete` declares every generated file and PDF page assigned. `partial`
keeps synthetic PDF page 2 unresolved and records a blocking `unassigned-page`
exception. `invalid-hidden-page` claims `prepared` while omitting synthetic PDF
page 2; the fixture factory rejects it with the stable `unassigned-page` code.

Only JSON documents are checked in. Tests materialize the tiny synthetic PDF
and XLSX files in their temporary directories.
