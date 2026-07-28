# 001 - Spec-Based Development

**Purpose:** Document new features in structured specs before implementation to ensure consistency and enable design review

**Status:** Implemented (2026-05-07)

## Requirements

- Write specs before coding new features
- Use sequential numbering (001, 002, 003...)
- Include design rationale and key decisions
- Keep specs focused on design, not implementation details
- Reference spec numbers in commit messages during implementation

## Design Approach

- Files named `XXX-{feature-name}.md` in `docs/spec/`
- Standard template focusing on purpose, requirements, design approach
- Status tracking: Draft -> Approved -> Implemented
- Update [000-specs.md](000-specs.md) when specs introduce new patterns

## Implementation Notes

- See [000-specs.md](000-specs.md) for code templates
- Specs should be under 100 lines when possible
- Extract shared patterns rather than repeating across specs
- Focus on "why" decisions were made, not "how" to implement

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
