# CTV Intake Contract v2 compatibility

Producers and consumers must match major version `2`. A v1 consumer is not
compatible with a v2 package and must not reinterpret it as v1.

V2 requires `assignments.json`; it permits repeatable `evidence` artifacts and
uses closed document shapes. `validation-report.json` is a generated receipt,
not a declared manifest artifact.

V2 contract fixtures contain only synthetic values. `schema-example` illustrates
closed document shapes, not a materialized package. Semantic complete packages
come from the production-backed Task 5 fixture factory.
