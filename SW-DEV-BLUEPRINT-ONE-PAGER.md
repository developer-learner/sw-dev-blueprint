# SW Dev Blueprint — What It Does and How It Works

**SW Dev Blueprint is a reusable system for building software with AI while keeping quality, safety, and completion under mechanical control.** It starts as a GitHub project template and provides the roles, documents, scripts, tests, and safeguards needed to turn a plain-language product idea into working software. Its central principle is simple: AI can propose and create, but it should not be trusted to decide whether its own work is correct.

## What it does

The Blueprint organizes AI-assisted development into a small production line. A person describes the desired product and remains responsible for business intent and final acceptance. AI systems then translate that intent into a product specification, a technical contract, an implementation plan, and code. At every stage, software-based checks validate the output before it can move forward.

This approach addresses the most common problems in AI coding: changing requirements mid-build, invented interfaces, oversized or incomplete changes, unsafe execution, silent failures, and an AI declaring success without evidence. Instead of relying on a long prompt or an agent's memory, the Blueprint stores the important decisions in versioned files and enforces them with tests, schemas, hashes, and workflow gates.

## How it works

1. **Describe the outcome.** The user explains what should be built in ordinary language, including the users, core behavior, and acceptance expectations.

2. **Create the specification.** A high-capability AI acting in the Technical Program Manager (TPM) role converts that intent into a product requirements document, technical design, machine-readable contracts, and acceptance tests. These artifacts define what the system must do and which files, APIs, data structures, and user-interface elements are allowed.

3. **Freeze the definition of done.** Before coding begins, automated checks confirm that the specification and tests are internally consistent and buildable. Once those checks pass, the approved artifacts are versioned and hash-locked. The coding AI cannot edit the tests or move the goalposts to make its implementation appear successful.

4. **Plan small, bounded tasks.** An Engineering Manager (EM) AI turns the frozen specification into a dependency-ordered plan. Each task is intentionally small—normally one file—and must map to specific contracts and tests. A validator rejects incomplete, circular, oversized, stale, or out-of-scope plans.

5. **Build one task at a time.** A coder AI returns the contents of a single file for each task. It does not receive direct access to the filesystem; the orchestration scripts inspect its response and write the file. The relevant frozen tests run immediately, so errors are found close to the change that caused them.

6. **Escalate failures instead of hiding them.** A failed task gets a limited retry. Repeated failure is diagnosed by the EM and may produce a revised task brief, a new plan, or a structured escalation package for the TPM. The pipeline does not silently skip failures or retry indefinitely until it gets a lucky result.

7. **Verify and accept the result.** Completion is determined by the frozen acceptance tests, not by an AI's opinion. Tests execute in an isolated container with no network access and read-only access to the project. After the automated checks pass, the user opens the product and confirms that the real experience is right. Human acceptance remains the final step.

## The operating model

The system separates responsibilities across four roles: the **user/CEO** owns intent and final acceptance; the **TPM** defines the product and its acceptance tests; the **EM** creates the implementation plan; and the **coder** produces narrowly scoped code. A shell-based orchestrator owns the procedure and moves artifacts between these roles. This separation reduces the chance that one AI can invent the requirements, implement them, weaken the tests, and approve its own work.

In the standard setup, local AI models run on the host computer, the pipeline operates inside Linux, and generated code is tested inside a disposable Podman container. Git provides history and recovery, while ledgers preserve completed work, recurring test flakes, decisions, and escalation details across sessions.

## The result

SW Dev Blueprint turns AI coding from an open-ended conversation into a repeatable, evidence-driven engineering process. It does not guarantee that AI will produce perfect code, and passing tests do not replace human product judgment. What it provides is a disciplined way to contain mistakes, preserve requirements, make failures visible, and establish a trustworthy answer to the question: **Is the software actually done?**
