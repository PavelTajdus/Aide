# Skill: Memory

## When to activate

### Saving (proactively, SILENTLY — do not announce to user)
When an important fact comes up in conversation, save it WITHOUT asking:
- Decisions ("switch to Shopify for EU store", "use PostgreSQL for the new project")
- Preferences ("no emails on Monday morning", "prefer X over Y")
- Contacts and relationships ("Alex = co-founder of ProjectX")
- Project status ("website redesign ~70% done")
- Important deadlines and numbers
- Anything that should survive between conversations

### Searching (at the start of a new thread)
On the first message in a new thread/conversation:
1. Search memory for keywords from the user's message
2. If the topic matches a file in `/knowledge/`, load it
3. Use found context for a better response

### Explicit commands
- "remember", "save to memory" → save
- "what do you know about...", "do you remember..." → search
- "forget", "delete from memory" → forget

## Steps

### Save
```
python $AIDE_ENGINE/core_tools/memory_manage.py add --text "..."
```

### Search
```
python $AIDE_ENGINE/core_tools/memory_manage.py search --query "..."
```

### List
```
python $AIDE_ENGINE/core_tools/memory_manage.py list
```

### Delete
```
python $AIDE_ENGINE/core_tools/memory_manage.py forget --id "UUID"
```

## What NOT to save
- Trivial facts already in CLAUDE.md
- Temporary things ("meeting today at 3pm")
- Duplicates — search before saving to check if already in memory

## Expected output
- When saving: save silently, do not comment (unless user explicitly asked)
- When searching: return relevant results concisely
