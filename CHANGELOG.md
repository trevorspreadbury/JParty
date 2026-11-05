# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Bugs identified in post-tournament review (to be filled in as fix PRs merge).

## [3.0.0-rc.1] - 2026-05-02

Build used at a tournament in May 2026. Reports its version as `2.0.2`
internally because the version string was not bumped before the event.

### Added
- Frankengames: compose boards from rounds/categories of multiple source games,
  with configurable Daily Doubles (#38, #40).
- Stats tracking (#28) and score correction (#26, #27).
- Question media selection and review workflow before game start (#25).
- Game caching and welcome screen updates (#22, #24).
- Audience participation button and "stumped" sound (#33).
- Saved game state and resume (#9).
- Test suite (#15).

### Changed
- Restructured the codebase into app/services/domain/ui/web layers (#16, #43).
- Games with missing clues can now be played.

### Fixed
- Lectern countdown bug (#32).
- Infinite recursion on Frankengames with media.
- Audio thread handling; added a silent buffer to `stumped.wav`.

[Unreleased]: https://github.com/trevorspreadbury/JParty/compare/v3.0.0-rc.1...dev
[3.0.0-rc.1]: https://github.com/trevorspreadbury/JParty/releases/tag/v3.0.0-rc.1
