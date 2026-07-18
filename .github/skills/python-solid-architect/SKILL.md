---
name: python-solid-architect
description: 'Use when: generating, reviewing, or refactoring Python code with SOLID design principles, dependency injection, ABC abstractions, PEP 484 typing, or clean architecture boundaries.'
---

# Python SOLID Architect

## Purpose

Use this skill to convert messy, tightly coupled, or legacy Python code into clean, scalable architecture, or to generate new Python code that follows the five SOLID design principles.

## When to Use

- Generating new Python modules, services, or domain logic where architecture matters
- Refactoring tightly coupled Python code
- Reviewing Python code for SOLID violations
- Introducing dependency injection, abstract base classes, or clean architecture boundaries
- Separating domain logic from infrastructure concerns such as databases, APIs, file I/O, and logging

## Architectural Standards

1. Single Responsibility Principle: separate core business domain logic from infrastructure utilities such as database access, external APIs, file I/O, and logging.
2. Open/Closed Principle: use Python's built-in `abc` module when abstractions are needed so behavior can be extended without modifying core code.
3. Liskov Substitution Principle: subclasses must be substitutable for parent classes. Do not override methods to intentionally break behavior, alter return types, or raise `NotImplementedError` for required behavior.
4. Interface Segregation Principle: keep interfaces tiny and single-purpose. Prefer duck typing or lightweight ABCs over large interfaces.
5. Dependency Inversion Principle: high-level logic must depend on abstractions, not concrete implementations. Inject dependencies instead of instantiating them inside constructors.

## Code Standards

- Use explicit PEP 484 type hints on all function and method parameters.
- Use explicit return type annotations on all functions and methods.
- Prefer small, cohesive classes and functions over broad multipurpose objects.
- Keep infrastructure adapters behind abstractions when high-level application logic depends on them.

## Workflow

1. Identify the Python behavior or module being generated, reviewed, or refactored.
2. Check for SOLID risks before editing or proposing code.
3. Design around small abstractions only where they reduce coupling or support extension.
4. Provide functional Python code that follows the standards above.
5. Include a `SOLID Compliance Audit` explaining how the design satisfies SRP, OCP, LSP, ISP, and DIP.

## SOLID Compliance Audit Format

When this skill produces or substantially refactors Python code, include this audit:

```markdown
## SOLID Compliance Audit

- SRP: Explain each class or function's single responsibility.
- OCP: Explain how behavior can be extended without modifying stable core code.
- LSP: Explain why subclasses or implementations are substitutable for their abstractions.
- ISP: Explain how interfaces stay focused and client-specific.
- DIP: Explain which high-level code depends on abstractions and how dependencies are injected.
```
