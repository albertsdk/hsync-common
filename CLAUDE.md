# Project Rules & Coding Guidelines (Python)

This document defines the strict architectural, development, and code-reuse rules for the Python codebase. Claude must strictly adhere to these guidelines at all times.

---

## 📚 Documentation Maintenance (Dual-Docs System)

The project maintains two distinct documentation environments. You must understand the difference and maintain both appropriately:
1. **`llm-wiki/` (Internal/Agent Knowledge Base)**: An agent-readable, structured map of the application's architecture, logic, and internal code references.
2. **`docs/` (End-User Technical Documentation)**: Human-readable documentation, user guides, and public API references meant for the final user.

### 1. Docs-First Workflow (Mandatory)
* **Read Before Exploring or Modifying Code**: Before exploring or modifying application code, you **MUST** first consult the internal wiki, starting from `llm-wiki/README.md`, and then drill down into the specific `llm-wiki/` file(s) relevant to the task. Administrative, repository-inspection, and documentation-only operations may use a proportionate subset of this workflow.
* **Index-Driven Navigation**: Use `llm-wiki/README.md` as the map: identify which module/feature/data-model docs are relevant, read them, and follow their `path/to/file.py:line` references to reach the right code directly instead of blindly searching the whole repository.
* **Docs Guide the Search**: Treat `llm-wiki/` as the first search surface. Codebase-wide exploration is a **fallback** for what the wiki does not yet cover.
* **Bootstrap on Absence**: If a specific doc does not exist or lacks relevant content, note the gap and create/extend it as part of the task. A missing doc is never an excuse to skip the docs-first step.

### 2. Mandatory Dual-Synchronization
* **Code & Docs Are One Change**: Whenever you **add, modify, or remove** any relevant element of the application, you **MUST** update the documentation **within the same task**.
* **Assess the Impact (The Dual Update)**:
  * *Internal Changes* (Refactoring, internal schemas, private logic): You must update the relevant files in **`llm-wiki/`**.
  * *User-Facing Changes* (Public APIs, CLI commands, features, configuration files): You must update the internal architecture in **`llm-wiki/`** AND the user guides/technical specs in **`docs/`**.
* **No Stale Docs**: Leaving either `llm-wiki/` or `docs/` out of sync with the code is **STRICTLY PROHIBITED**. If you cannot fully document a change in both places, the task is **not complete**.
* **Semantic Changes Only**: Update documentation when the documented architecture, behavior, contract, configuration, or operational procedure changes. Pure formatting, behavior-preserving refactoring, and test-only changes do not require documentation churn unless they reveal that existing documentation is inaccurate.

### 3. Directory Structures
Both doc sets follow a recommended **baseline** layout; adapt the exact file set
to the project's nature (library, service, CLI, GUI/mobile app) and keep each
index `README.md` honest about what actually exists.
* **LLM-Wiki (`llm-wiki/`) - Agent Optimized** (baseline):
  * `llm-wiki/README.md` — index / table of contents linking every other doc.
  * `llm-wiki/architecture.md` — high-level system overview and component interactions.
  * `llm-wiki/modules/<module>.md` — internal responsibilities, key classes/functions.
  * `llm-wiki/data-models.md` — the project's core data structures/schemas and their relationships (whatever the language uses: classes, dataclasses, structs, records, DTOs, enums…).
  * `llm-wiki/decisions.md` — log of relevant architectural/design decisions.
  * Add, rename, split or omit files as the project requires (e.g. extra `modules/*` pages); a doc is justified only when it maps to real code.
* **User Docs (`docs/`) - Human Optimized** (only the subset that applies):
  * `docs/README.md` — welcome page, installation, and quickstart for the user.
  * `docs/usage.md` — how to use the software (CLI commands, UI features, or library API).
  * Add domain-appropriate guides when relevant (e.g. `docs/api.md` for a service exposing endpoints; configuration/security/setup guides) and omit what does not apply (an internal library or an app with no public API needs no `api.md`).

### 4. Content & Style Rules
* **For `llm-wiki/` (Concise & Factual)**: Write for an LLM consumer. Use bullet lists, tables, and clear headings. Avoid duplication. Reference the relevant source location using the `path/to/file.py:line` pattern so the doc stays anchored to the implementation. Do not duplicate large code blocks; describe intent and point to the code.
* **For `docs/` (Clear & Explanatory)**: Write for a human developer/user. Provide context, practical examples, and clear step-by-step guides. Do NOT expose internal routing or private function names here; focus on the public interface.
* **Keep the Indexes Honest**: When you add, rename, or delete a doc file in either directory, update the respective `README.md` in the same change.

### 5. Removal Discipline
* **Delete With the Code**: When a feature or logic is **removed**, delete or update its documentation in BOTH `llm-wiki/` and `docs/` in the same change. Consistent with the project's *Zero Backward Compatibility* stance, do **NOT** keep documentation describing removed functionality.

---

## ⚠️ Domain-Critical Rules

* **LAN Discovery & Master Election**
  Before modifying any logic related to these mechanisms, you **MUST** read and follow the specifications outlined in `hsync-common/docs/lan-protocol.md`.

* **Packaging WD My Cloud OS5**
  Any change to CLI flags, environment variables (`HSYNC_*`), or user-facing behaviors/defaults **REQUIRES** a synchronous update to `hsync-client/packaging/wd-os5`:
  * `Apkg/start.sh`
  * `Apkg/install.sh`
  * `Apkg/web/index.html`
  * `Apkg/web/app.js`
  * `Apkg/web/config_get.php`
  * `Apkg/web/config_set.php`
  * i18n translations `Apkg/web/i18n/*.json`
  * `README.md`

  Keep flags, key whitelists, and i18n strings strictly aligned across all five languages (EN, IT, DE, ES, FR).

---

## 🚀 Evolution & Breaking Changes

* **Zero Backward Compatibility**
  There are no existing production environments. **Backward compatibility is NOT required when the requested design intentionally changes a contract.** Prioritize the ideal architecture and optimal design over supporting legacy states, but do not introduce unrelated breaking changes. Update all affected consumers, models, tests, schemas, fixtures, protocol versions, persisted assumptions, and documentation atomically.

* **Clean Breaking Changes**
  Treat every major intervention as a completely new version of the application. Implement rigid contracts, mandatory protocol versions, and strict data fields. **CATEGORICALLY REMOVE** shims, legacy channels, migration phases, and fallback logic.

---

## ✅ Implementation Quality Gate

Every code change must pass a bounded implementation and verification cycle before the task may be considered complete.

### 1. Acceptance Criteria Before Implementation

Before modifying code, identify observable behavior and affected consumer/protocol contracts; failure cases, boundaries, security implications, and state transitions; existing implementation and tests; reusable models/utilities; and impacts on client, server, desktop, and Android mirrors. Do not invent unsupported requirements. Apply proportionally to trivial documentation-only or formatting-only changes.

### 2. First Implementation Pass

Implement the smallest complete change satisfying the acceptance criteria. Do not add speculative functionality, hide failures, weaken tests, or change unrelated code.

### 3. Mandatory Verification Pass

After implementation and before finalizing:

1. Re-read the request and acceptance criteria without assuming correctness.
2. Inspect the complete diff, including tests, schemas, golden fixtures, ADRs, changelog, and documentation.
3. Trace normal, invalid-input, empty/missing, limits, serialization, concurrency, cancellation, partial-failure, path-validation, secret-exposure, and injection paths where applicable.
4. Verify consistency across models, type hints, serialization, protocol versions, JSON schemas, fixtures, callers, all consumers, and documentation.
5. Run targeted `poetry run pytest` tests first. When practical, run full `poetry run pytest` and `poetry run ruff check .` checks configured by the project.
6. Correct every issue found and rerun affected checks.

Diff inspection and executed checks are required; stating that the implementation was reviewed is insufficient.

### 4. Regression and Contract Tests

Every bug fix needs a regression test that fails before and passes after the fix. New behavior must cover success and relevant failure/boundary paths. Every protocol change must update generated schemas and committed fixtures, test drift, and update affected Python consumers and Android parity tests atomically. A test may be omitted only when genuinely impractical, with reason and alternative verification reported.

### 5. Bounded Correction Cycle

Fix issues found and repeat relevant verification for at most two review-and-correction cycles unless the user requests more. Do not finalize with known failures. Report environmental or pre-existing blockers precisely, and never claim an unexecuted check passed.

### 6. Definition of Done

Completion requires satisfied acceptance criteria, complete diff review, passing relevant checks, adequate tests, synchronized protocol artifacts/consumers/documentation, and no known correctness or security defect. The final response must state changes, commands and outcomes, omitted checks and reasons, and remaining risks.

For protocol/API contracts, authentication, secrets, destructive sync, persistence, or concurrency changes, request an independent review when available; this does not replace tests or self-verification.

---

## 🐍 Python Standards & Code Reuse (`*.py`)

### 1. Strict DRY & Duplication Prevention
* **Pre-implementation Check**: Before writing any new function, component, or logic, you **MUST** search the relevant module and shared utility/model locations for an existing implementation. Expand to a repository-wide search only when the wiki and local search are insufficient.
* **No Copy-Paste-Modify**: Copying, pasting, and slightly modifying existing code snippets for a new use case is **STRICTLY PROHIBITED**.
* **Refactoring over Duplication**: If *similar* (but not identical) logic already exists, **DO NOT** create a duplicate. Instead, refactor the existing code to make it more generic, parameterized, and reusable. Briefly explain your refactoring logic when doing so.
* **Rule of Three**: If you identify or need the same logic/code block for a second time, treat it as a warning. If requested for a third time, you **MUST** extract it into a standalone utility function, helper, or common base class.
* **No Inline Helpers**: Writing nested or inline helper functions inside main functions is **PROHIBITED** if the logic is generic and extractable. Always promote exportation and centralized reuse.
* **Semantic Reuse over Superficial Similarity**: Extract shared logic only when behavior, invariants, and reasons to change are the same. Prefer small local duplication over an incorrect or unstable abstraction.

### 2. Typing & Data Models
* **Centralized Models**: Strictly use type hints. For data structures, **ALWAYS** reuse existing models located in the `schemas/` or `models/` directories (Pydantic or Dataclasses).
* **No Manual Parsing**: **DO NOT** perform manual parsing or complex dictionary navigation (e.g., `dict.get()`) if a Pydantic class already exists to validate and instantiate that specific payload type.

### 3. Modularity & Maintainability
* **File Responsibility Control**: Split a file when it contains multiple independently changing responsibilities, not merely because of line count. Do not perform unrelated structural refactoring as part of a narrowly scoped fix.

---

## 📝 Changelog Maintenance

Before completing any task that introduces a user-facing change, bug fix, or
notable internal improvement, evaluate whether the change warrants an entry in
`CHANGELOG.md` following the [Keep a Changelog](https://keepachangelog.com/)
format. Add an entry under an `## [Unreleased]` section when relevant.

Irrelevant for: typo fixes, purely internal refactors with no behavioral change,
CI/formatting-only changes, or doc updates that don't document new features.
