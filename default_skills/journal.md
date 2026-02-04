# Skill: Journal

## Kdy se aktivuje
- Uživatel chce zapsat poznámku do deníku/journalu.
- Fráze jako: "zapiš do deníku", "journal", "deník".

## Kroky
1. Připrav krátký zápis (max 1–5 odstavců).
2. Zavolej core tool:
   `python $AIDE_ENGINE/core_tools/journal_write.py --text "..."`
   (nebo `python core_tools/journal_write.py ...` pokud jsi ve workspace)
3. Potvrď, že zápis proběhl.

## Očekávaný výstup
- Krátké potvrzení + případně souhrn toho, co bylo zapsáno.
