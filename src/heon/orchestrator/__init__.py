"""
Orchestrator — Multi-agent execution loop for the HEON analysis engine.

Inspired by dexter's Agent class architecture:
  - Iterative tool-calling loop with max iterations
  - Micro-compaction for context management
  - Scratchpad for tool result tracking
  - Concurrent read-only tool execution
  - Token/step safety limits

This orchestrator coordinates the complete analysis pipeline:
  1. Data gathering (free sources only)
  2. Red flag scanning
  3. Pillar evaluation
  4. Scorecard computation
  5. Validation gate
  6. Report generation
"""
