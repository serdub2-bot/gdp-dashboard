# FM 2008 executable — static reverse-engineering pass

## Scope and reproducibility

This is a new, bounded static-analysis pass over the executable in `inbox/fm.zip`; it does not claim to reverse engineer the entire game. The archive member was extracted into `/tmp/fm_re/fm.exe`, not in place. SHA-256 is `9725365b4996622c122e37f9f91c903c2ccef112f32121d33db000ed9012d42b` (22,249,472 bytes), matching the existing inventory. No game process was run; the supplied EXE, save games, database files, and patches were not edited.

The pass examined the PE32 x86 export table, mapped export VAs back to the `.text` bytes, disassembled entry prefixes with Capstone, grouped duplicate export addresses, and followed selected shared helper paths. For bulk exports, the CSV records only a linear decode up to the first `RET`, capped at 0x400 bytes. That is a reproducible prefix survey, **not** complete function boundary recovery, a complete call graph, or semantic decompilation. Symbols/PDB were not available.

Re-run the inventory from the repository root (Capstone 5.x required):

```sh
python3 -m pip install --target /tmp/fm_re/deps capstone
mkdir -p /tmp/fm_re
unzip -p inbox/fm.zip fm.exe > /tmp/fm_re/fm.exe
sha256sum /tmp/fm_re/fm.exe
PYTHONPATH=/tmp/fm_re/deps python3 \
  'fm 08 for devin/reverse_engineering/export_api_analysis.py' \
  --exe /tmp/fm_re/fm.exe \
  --exports 'fm 08 for devin/inventory/exports.csv' \
  --out 'fm 08 for devin/reverse_engineering/inventory'
```

## Verified executable identity

- PE32 / x86; image base `0x00400000`.
- SHA-256 and size above match the existing EXE report.
- This pass treats virtual addresses as VA (not RVA); the analysis script checks PE section mappings before reading code.

## Export surface

The export directory has **382 named exports at 370 distinct entry VAs**. Duplicate addresses are aliases, not separate machine-code bodies. Suffix counts are a naming heuristic, not a formal API taxonomy:

| Name suffix | Export names | Distinct entry VAs |
|---|---:|---:|
| `rules` | 179 | 173 |
| `comps` | 75 | 70 |
| `settings` | 63 | 63 |
| `teams` | 61 | 61 |
| `seeding` | 3 | 3 |
| `comp` | 1 | 1 |

Four entry addresses are shared among multiple export names. The most striking alias group is seven regional names at VA `0x00871a60`:

- `asi_get_minimum_division_teams`
- `eng_register_teams_for_comps`
- `ger_register_teams_for_comps`
- `jap_setup_comps`
- `nam_register_teams_for_comps`
- `sam_register_teams_for_comps`
- `ukr_register_teams_for_comps`

At `0x00871a60`, the first instruction byte is `C3` (`ret`); following bytes in the slot are `CC` (`int3`) padding. Thus these seven export names resolve to the same one-byte return stub in this exact file. This proves the exported entries have no body at that address; it does not prove why they are empty, whether another mechanism supplies equivalent behavior, or whether this is an intentional product configuration.

Other shared-entry groups are in [`inventory/export_name_groups.csv`](inventory/export_name_groups.csv). The full export-to-VA and prefix-call inventory is [`inventory/export_entrypoints.csv`](inventory/export_entrypoints.csv); suffix totals are in [`inventory/export_suffix_counts.csv`](inventory/export_suffix_counts.csv).

## Common setup helper path

A direct-call count from the initial block of each export finds VA `0x00d35180` in 381 of the 382 export prefixes, and `0x00c933f0` in 324. These are strong shared infrastructure anchors for the exported regional setup API. Counts are based on the bounded linear prefixes described above; they should not be read as full-function call-graph totals.

### VA `0x00c933f0`: indexed object-slot accessor/initializer (behavioral description)

The inspected body uses a caller-supplied integer as an index into a global pointer array (global addresses `0x01b1f0c8` and `0x01b1f0cc` in this image). It grows the pointer array when the index exceeds the current count, initializes missing slots, and calls the allocator-like helper at `0x00f479e0` for storage. A newly created object receives vtable pointer `0x0159f68c`, stores the requested index at offset `+0x14`, and has further pointer/capacity-like fields initialized before return.

This description follows visible memory operations and control flow; the class represented by that vtable and the exact meanings of all fields remain unknown. The relevant body is in the generated export-prefix record for callers and can be re-disassembled at `0x00c933f0`.

### VA `0x00d35180`: shared indexed-entry update helper (behavioral description)

The helper is called by nearly all exports in the observed prefix. It reads a global context at `0x01b1ecd0`, accepts multiple arguments including 16-bit values, treats `0xfffe` and `0xffff` as special cases, follows object vtables, writes WORDs at offsets such as `+0x4`, `+0x6`, and updates a byte flag at offset `+0x29` on some validation paths. This is consistent with a shared record/configuration-entry update routine used by the exported setup functions, but the field names and business meaning are not recoverable from these operations alone.

### VA `0x00f479e0`: allocation path (behavioral description)

The routine reads the global manager pointer at `0x01b20584`, passes the requested size to `0x011304d2`, and if allocation returns null for a nonzero request, calls `0x00f47780` on the manager and retries. The visible use from `0x00c933f0` supports describing it as an allocation/manager path. What `0x00f47780` does beyond this recovery/retry path is not asserted here.

## Regional API examples

These samples establish code organization, not a full competition-rule specification:

- `eng_setup_comps` at `0x00f068c0` calls `0x00c933f0` repeatedly with immediate index `0x240` and dispatches through a series of regional helper addresses (for example `0x00f02df0`, `0x00f02730`, `0x00f02e90`, `0x00f02fc0`). This is consistent with obtaining/updating indexed entries and applying region-specific setup routines. Exact object types and competition meanings are unresolved.
- `eng_setup_discipline_rules` at `0x00f01fd0` calls `0x00df6be0`, `0x00df6a70`, `0x00df6ab0`, and `0x00df6a90` with immediate arguments. The other `*_setup_discipline_rules` exports commonly reference the same helper family with different constants. This is evidence for a shared rule-building mechanism; the constants have not been mapped to named rule fields.
- `eng_setup_fixture_rules` at `0x00f071f0` obtains a value through `0x00f479e0`, then calls `0x004374c0` and `0x00c952b0` along the inspected path.
- `eng_setup_transfer_rules` at `0x00f07740` obtains an allocation/manager result for key `0x5c`, then tail-jumps to `0x00f071d0`; the target implementation needs separate analysis before assigning semantics.
- `eng_get_settings` at `0x00f01e90` and other regional `*_get_settings` functions use `0x00f479e0` with a small integer and then call repeated helper families (`0x00d637c0`, `0x00d63c10`, `0x00e48d30`, `0x00e48dc0` among the England prefix). These names strongly suggest configuration setup, but exact return object layout and field names remain unconfirmed.

### Interpretation limits

The export names give unusually useful anchors for the game's country/region configuration API. But naming is not symbol information: the precise C++ signatures, object classes, constant enums, field schemas, and lifecycle/ordering guarantees remain unknown. Indirect virtual calls are recorded as such; their targets have not been globally devirtualized. The analysis does not state that any export is reached in a normal game startup.

## Suggested next reverse-engineering tranche

1. Recover all basic blocks for the shared helpers (`0x00d35180`, `0x00c933f0`, `0x00f479e0`) and classify their callers by call-site arguments.
2. Trace the regional setup functions into helper bodies and compare countries with different settings to map constant arguments to actual fields.
3. Find callers of the export groups to establish when/how regional modules are invoked.
4. Recover type names or vtables for the object at `0x00c933f0`'s new-slot vtable and for objects updated by `0x00d35180`.
5. Keep semantic claims separate from observed control flow until validated by symbols, a clean comparison build, or a controlled disposable test.

No match simulations, save editing, binary patching, or runtime experiments are part of this pass.
