# Spec Delta

## MODIFIED Requirements

### Requirement: Availability of a newer cobble release is determined

Cobble SHALL determine the latest stable release of cobble from the project's published releases, compare it with the running version, and report whether an update is available together with the latest version, a link to that release's page, that release's title, its publish date, its release notes as published (Markdown text), and when the check was last performed. Drafts and pre-releases SHALL NOT be treated as available updates. Release notes that were published empty SHALL be reported as absent rather than as an empty string.

#### Scenario: A newer release exists

- **WHEN** the latest stable release is a higher version than the running version
- **THEN** an update is reported as available
- **AND** the latest version and a link to its release page are reported
- **AND** its title, publish date, and release notes are reported

#### Scenario: Running the latest release

- **WHEN** the latest stable release is the same version as the running version
- **THEN** no update is reported as available
- **AND** that release's notes are still reported

#### Scenario: Running a version newer than the latest release

- **WHEN** the running version is higher than the latest stable release (for example, a development build)
- **THEN** no update is reported as available

#### Scenario: Only a pre-release is newer

- **WHEN** the only release newer than the running version is a draft or pre-release
- **THEN** no update is reported as available

#### Scenario: Release published without notes

- **WHEN** the latest stable release has empty or whitespace-only notes
- **THEN** the release is reported normally
- **AND** its notes are reported as absent

#### Scenario: A cached result predates release notes

- **WHEN** cobble starts with a cached release check result that was recorded before release notes were captured
- **THEN** the next check fetches the release in full rather than accepting a "not modified" answer for the cached result
- **AND** the notes are reported once that check succeeds

## ADDED Requirements

### Requirement: Every published release carries release notes from the changelog

The project SHALL keep a changelog in the repository with one section per released version. Publishing a release SHALL use that version's changelog section as the release's notes. A release whose version has no changelog section, or an empty one, SHALL NOT be published.

#### Scenario: Tag with a changelog entry

- **WHEN** a version tag is pushed and the changelog has a non-empty section for that version
- **THEN** the release is published with that section's text as its notes

#### Scenario: Tag without a changelog entry

- **WHEN** a version tag is pushed and the changelog has no section, or an empty section, for that version
- **THEN** the release is not published
- **AND** the publishing job fails with a message naming the missing version
