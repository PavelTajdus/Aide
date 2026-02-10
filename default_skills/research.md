# Skill: Research

## When to activate
- User requests research, comparison, summary, best practices, or recommendations.

## Steps
1. Clarify the scope (topic, time range, desired output).
2. Use Perplexity search for aktuální informace z webu:
   ```bash
   cd /opt/aide/workspace && python3 tools/perplexity_search.py "dotaz"
   ```
   Pro hloubkový research: `--model sonar-deep-research`
3. Summarize results concisely with clear conclusions.

## Expected output
- Structured bullet points + recommendations + zdroje (citace z Perplexity).
