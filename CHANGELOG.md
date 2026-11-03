# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- The wiki anchor checker accepts a `file.py::Class.attribute` anchor that
  points at a bare annotated declaration (`_link_down: bool`) or at a
  `self.x = ...` assignment instead of reporting it as a broken anchor.
