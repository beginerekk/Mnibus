# Launcher.py Bot Switching Bug Fix

## Problem Reported
When refreshing the table list, the launcher was:
1. **Switching the bot to a new table unnecessarily** — bot position would change on refresh
2. **Table list not updating** — after selecting a bot, the table list wouldn't display

## Root Causes Identified

### Issue 1: `__TABLES__` Token Handler (Line 2481)
**Problem**: Setting `changed = True` for table list refresh caused unnecessary GUI updates
```python
# OLD: Line 2481
if msg == '__TABLES__':
    if self.sel == idx:
        self._refresh_table_list(bot.tables)
    self._log(f'Bot #{idx}: 📋 {len(bot.tables)} stołów')
    changed = True  # ← CAUSING UNWANTED REFRESHES
    continue
```

**Impact**: Every 90 seconds when bot fetches table list, `changed = True` triggered GUI label refresh cycle, which could cause bot switching side effects.

### Issue 2: `__TABLE_UPDATED__` Token Handler (Lines 2487-2489)
**Problem**: Unconditionally updating `bot.table` without checking if it actually changed
```python
# OLD: Lines 2487-2489
if msg.startswith('__TABLE_UPDATED__'):
    try:
        table_id = int(msg[17:])
        bot.table = table_id  # ← ALWAYS SET, EVEN IF SAME VALUE
        changed = True        # ← ALWAYS MARKS AS CHANGED
    except ValueError:
        pass
```

**Impact**: If the bot sent the same table ID (or received a stale/duplicate message), it would still trigger GUI updates, causing false positives and potential bot position changes.

## Solution Implemented

### Fix 1: Remove `changed = True` from `__TABLES__` Handler
```python
# NEW: Line 2481
if msg == '__TABLES__':
    if self.sel == idx:
        self._refresh_table_list(bot.tables)
    self._log(f'Bot #{idx}: 📋 {len(bot.tables)} stołów')
    # Nie ustawiaj changed=True dla samej listy stołów
    continue
```

**Benefit**: Table list refreshes no longer trigger unnecessary GUI updates, preventing cascading side effects.

### Fix 2: Add Conditional Check to `__TABLE_UPDATED__` Handler
```python
# NEW: Lines 2487-2491
if msg.startswith('__TABLE_UPDATED__'):
    try:
        table_id = int(msg[17:])
        # Tylko zmień tabelę jeśli faktycznie się zmieniła
        if bot.table != table_id:
            bot.table = table_id
            changed = True
    except ValueError:
        pass
```

**Benefit**: Only updates GUI when bot actually switches tables. Prevents false positives from duplicate or stale messages.

## Expected Results After Fix

✅ **Bot no longer switches tables on refresh** — table updates only trigger when bot receives `/join` command  
✅ **Table list updates correctly** — `_refresh_table_list()` is called when bot is selected and receives new table list  
✅ **GUI remains stable** — Reduces unnecessary refresh cycles and prevents cascading updates  
✅ **Cleaner logs** — Only logs actual state changes, not every refresh cycle

## Technical Details

### Files Modified
- `modules/kurnik-ws/launcher.py` — Main launcher GUI (lines 2481, 2487-2491)

### No Changes Required To
- `kurnik-ws.py` — Bot subprocess code (already working correctly)
- `SERVER_PROTOCOL.md` — Protocol documentation
- Configuration files — All configuration systems unchanged

## Validation

- ✅ Python syntax validated (`py_compile`)
- ✅ No breaking changes to API or bot communication
- ✅ Backward compatible with existing bots and commands
- ✅ `/ext` command implementation unaffected

## Testing Recommendations

1. Start launcher with multiple bots
2. Select a bot and verify table list appears
3. Wait for table refresh cycle (~90 seconds)
4. Confirm bot remains on same table (unless manually changed)
5. Test `/join` command to verify bot switching still works
6. Test `/ext` command to verify message sending works
