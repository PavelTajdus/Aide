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
Optional flags:
- `--type decision|contact|project|event|preference` — override auto-detected type
- `--tags "finance,seo"` — override auto-detected tags
- `--project "acg-stores"` — override auto-detected project
- `--shared` — save as shared/team memory (user_id=NULL, visible to all users)

### Search (two-layer retrieval)
Step 1 — compact index (~50 tokens/result):
```
python $AIDE_ENGINE/core_tools/memory_manage.py search --query "..." --compact
```
Step 2 — full details for selected IDs:
```
python $AIDE_ENGINE/core_tools/memory_manage.py get --ids "id1,id2,id3"
```
Full search (backwards compatible):
```
python $AIDE_ENGINE/core_tools/memory_manage.py search --query "..."
```
Filter options: `--type`, `--project`, `--limit N`

### List
```
python $AIDE_ENGINE/core_tools/memory_manage.py list
python $AIDE_ENGINE/core_tools/memory_manage.py list --compact
python $AIDE_ENGINE/core_tools/memory_manage.py list --type decision --project acg-stores
```

### Stats
```
python $AIDE_ENGINE/core_tools/memory_manage.py stats
```

### Delete
```
python $AIDE_ENGINE/core_tools/memory_manage.py forget --id "UUID"
```

### Archive (move old memories)
```
python $AIDE_ENGINE/core_tools/memory_manage.py archive --days 30
```

### Migrate (JSON → SQLite, one-time)
```
python $AIDE_ENGINE/core_tools/memory_manage.py migrate
```

## What NOT to save
- Trivial facts already in CLAUDE.md
- Temporary things ("meeting today at 3pm")
- Duplicates — search before saving to check if already in memory

## Expected output
- When saving: save silently, do not comment (unless user explicitly asked)
- When searching: return relevant results concisely
