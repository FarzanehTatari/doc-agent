# Project Facts

<!-- Copy this file to project_lib/facts.md and edit. Format: `- [priority] text  #tag1 #tag2`. -->
<!-- Priority: critical | high | normal | low -->

## Naming Conventions

- [critical] Signal names use camelCase with a unit suffix (e.g. `vEgoSpeed_kmh`). #naming #signals
- [normal] Subsystem names use PascalCase. #naming

## Domain

- [high] Vehicle speed is always reported in km/h, never mph. #units

## Policy

- [critical] Never reference internal part numbers in generated documentation. #compliance

## Other

- [normal] Stateflow charts get state diagrams as Mermaid blocks. #stateflow
