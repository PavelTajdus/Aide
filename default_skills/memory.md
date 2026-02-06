# Skill: Memory

## Kdy se aktivuje

### Ukládání (proaktivně, TIŠE — neoznamuj uživateli)
Když v konverzaci zazní důležitý fakt, ulož ho BEZ ptaní:
- Rozhodnutí ("přecenit Fiberlogy od 1.3.", "používáme Shopify pro EU")
- Preference ("nechci emaily v pondělí ráno", "preferuji X před Y")
- Kontakty a vztahy ("Kuba = spoluzakladatel Printerhive")
- Stav projektů ("Sicca.cz ~70% hotovo")
- Důležité termíny a čísla
- Cokoliv co by mělo přežít mezi konverzacemi

### Vyhledávání (na začátku nového vlákna)
Při první zprávě v novém vlákně/konverzaci:
1. Prohledej memory podle klíčových slov z uživatelovy zprávy
2. Pokud téma odpovídá souboru v `/knowledge/`, načti ho
3. Použij nalezený kontext pro lepší odpověď

### Explicitní příkazy
- "zapamatuj si", "remember", "paměť" → uložit
- "co víš o...", "pamatuješ si..." → vyhledat
- "zapomeň", "smaž z paměti" → forget

## Kroky

### Uložení
```
python $AIDE_ENGINE/core_tools/memory_manage.py add --text "..."
```

### Vyhledání
```
python $AIDE_ENGINE/core_tools/memory_manage.py search --query "..."
```

### Seznam
```
python $AIDE_ENGINE/core_tools/memory_manage.py list
```

### Smazání
```
python $AIDE_ENGINE/core_tools/memory_manage.py forget --id "UUID"
```

## Co NEUKLÁDAT
- Triviální fakta co jsou v CLAUDE.md
- Dočasné věci ("dnes mám meeting v 15:00")
- Duplicity — před uložením hledej jestli to už není v memory

## Očekávaný výstup
- Při ukládání: tiše uložit, nekomentovat (pokud to uživatel explicitně nežádal)
- Při hledání: vrátit relevantní výsledky stručně
