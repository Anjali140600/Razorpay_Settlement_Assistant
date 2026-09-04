# Changelog

## [0.1.0.0] - 2026-09-04

### Added

- Added a dedicated JSON download for unsettled payments, including payment details, totals, and Instant Settlement eligibility.
- Added clear formula explanations that appear when users hover over each main settlement report metric.
- Added pending-payment labels and detail messages for instant-eligible, standard-settlement-only, and unknown eligibility states.

### Fixed

- Unsettled payment exports now exclude payments captured after the report cutoff date.
- Lifecycle report tables now render open and closed durations consistently without serialization warnings.
