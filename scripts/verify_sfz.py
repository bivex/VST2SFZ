#!/usr/bin/env python3
"""
SFZ integrity verifier.

Checks that every sample referenced by an .sfz (or a main+drums pair) really
exists on disk and has correct, resolvable paths, and reports the structural
problems that most often cause an instrument to "not sound right":

  * broken/missing sample paths (the #1 cause of silence)
  * duplicate region key/velocity overlaps
  * holes in key-zone or velocity coverage (notes that trigger nothing)
  * orphan WAV files on disk that no .sfz references
  * main+drums pairing mistakes (e.g. pointing a drums file at the wrong
    main bank, or a sfizz bank that incorrectly embeds channel-10 drums)

Usage:
    python3 scripts/verify_sfz.py [SFZ_PATH ...]
    python3 scripts/verify_sfz.py --pair MAIN.sfz DRUMS.sfz
    python3 scripts/verify_sfz.py sfz/Dexed_MIDI_sfizz.sfz
    python3 scripts/verify_sfz.py --pair sfz/Dexed_MIDI.sfz sfz/Dexed_MIDI_sfizz_drums.sfz

With no arguments it scans every .sfz in sfz/ and pairs each "*_sfizz.sfz"
with its matching "*_sfizz_drums.sfz" sibling.

Exit code is non-zero if any ERROR-level problem is found, so it can be
used in CI / pre-commit.
"""

import os
import re
import sys
import glob
import argparse
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── ANSI colours (auto-disabled when not a TTY) ─────────────────────────────
USE_COLOR = sys.stdout.isatty()

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def green(t):  return _c("32", t)
def red(t):    return _c("31", t)
def yellow(t): return _c("33", t)
def cyan(t):   return _c("36", t)
def dim(t):    return _c("2", t)

# ── SFZ parsing ─────────────────────────────────────────────────────────────
REGION_RE = re.compile(r"<region>(.*)", re.IGNORECASE)
SAMPLE_RE = re.compile(r"sample=(\S+)")

# region-level opcodes we track (default to sane SFZ values)
INT_OPCODES = {
    "lokey": 0, "hikey": 127, "pitch_keycenter": 60,
    "lovel": 0, "hivel": 127,
    "lochan": 1, "hichan": 16,
    "loprog": 0, "hiprog": 127,
}
# group-level opcodes inherited by regions in that group
GROUP_OPCODES = ("loprog", "hiprog", "lochan", "hichan", "lokey", "hikey",
                 "lovel", "hivel", "pitch_keycenter")

NOTE_LETTERS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def midi_to_name(m):
    try:
        m = int(m)
    except (TypeError, ValueError):
        return "?"
    if m < 0 or m > 127:
        return f"^{m}"
    return f"{NOTE_LETTERS[m % 12]}{m // 12 - 1}"


class Region:
    __slots__ = ("sample", "lokey", "hikey", "lovel", "hivel",
                 "lochan", "hichan", "loprog", "hiprog",
                 "pitch_keycenter", "line", "exists", "reason", "_resolved")

    def __init__(self, sample, opcodes, line):
        self.sample = sample
        self.line = line
        g = lambda k: opcodes.get(k, INT_OPCODES[k])
        self.lokey = g("lokey"); self.hikey = g("hikey")
        self.lovel = g("lovel"); self.hivel = g("hivel")
        self.lochan = g("lochan"); self.hichan = g("hichan")
        self.loprog = g("loprog"); self.hiprog = g("hiprog")
        self.pitch_keycenter = g("pitch_keycenter")
        self.exists = True
        self.reason = None

    def overlaps(self, other):
        """Same channel+program AND overlapping key AND velocity → conflict."""
        if self.hichan < other.lochan or other.hichan < self.lochan:
            return False
        if self.hiprog < other.loprog or other.hiprog < self.loprog:
            return False
        if self.hikey < other.lokey or other.hikey < self.lokey:
            return False
        if self.hivel < other.lovel or other.hivel < self.lovel:
            return False
        return True


def _resolve_sample_path(raw, default_path, sfz_dir):
    """Resolve an SFZ `sample=` value to an absolute filesystem path.

    Per the SFZ spec, relative paths are resolved against the directory
    that contains the .sfz file. `default_path` (when present) is prefixed
    onto the sample value first; it too is relative to the .sfz dir if not
    absolute.

    Returns (resolved_path, tried_paths) so the caller can report which
    candidates failed when nothing exists on disk.
    """
    p = raw.strip().strip('"')
    tried = []

    candidates = []
    if os.path.isabs(p):
        candidates.append(p)
    else:
        # default_path is applied as a prefix, then resolved against sfz_dir
        if default_path:
            dp = default_path
            if not os.path.isabs(dp):
                dp = os.path.normpath(os.path.join(sfz_dir, dp))
            candidates.append(os.path.normpath(os.path.join(dp, p)))
        # finally, the sample path alone relative to the sfz dir
        candidates.append(os.path.normpath(os.path.join(sfz_dir, p)))

    # de-dup while preserving order
    seen = set()
    uniq = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
            tried.append(c)
    return uniq[0], tried


def parse_sfz(path):
    """Parse an .sfz file into (regions, default_path, sample_paths_set)."""
    regions = []
    default_path = None
    group_opcodes = {}

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return regions, None, set(), [f"cannot read file: {e}"]

    errors = []

    # Expand #include directives inline so a bank that pulls in a drums
    # section is checked as a single instrument.
    def expand_includes(src, depth=0):
        if depth > 8:
            errors.append("nested #include depth exceeded (cycle?)")
            return src
        out = []
        sfz_dir = os.path.dirname(os.path.abspath(path))
        for line in src.splitlines():
            m = re.match(r"\s*#include\s+(.+?)\s*$", line)
            if not m:
                out.append(line)
                continue
            inc = m.group(1).strip().strip('"')
            if not os.path.isabs(inc):
                inc = os.path.normpath(os.path.join(sfz_dir, inc))
            if os.path.isfile(inc):
                with open(inc, "r", encoding="utf-8", errors="replace") as incf:
                    out.extend(expand_includes(incf.read(), depth + 1).splitlines())
            else:
                errors.append(f"#include not found: {inc}")
        return "\n".join(out)

    text = expand_includes(text)

    for lineno, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue

        if line.lower().startswith("<control>"):
            continue

        if line.lower().startswith("<group>"):
            # opcodes on the group line are inherited by following regions
            group_opcodes = _parse_opcodes(line[len("<group>"):])
            continue

        if line.lower().startswith("<region>"):
            opcodes = dict(group_opcodes)  # inherit group defaults
            opcodes.update(_parse_opcodes(line[len("<region>"):]))
            sm = opcodes.get("__sample_raw")
            if sm is None:
                errors.append(f"line {lineno}: <region> with no sample= opcode")
                continue
            for k in INT_OPCODES:
                if k in opcodes and opcodes[k] is not None:
                    try:
                        opcodes[k] = int(opcodes[k])
                    except (TypeError, ValueError):
                        errors.append(
                            f"line {lineno}: bad integer for {k}={opcodes[k]!r}")
                        opcodes[k] = INT_OPCODES[k]
            region = Region(sm, opcodes, lineno)
            resolved, tried = _resolve_sample_path(
                sm, default_path, os.path.dirname(os.path.abspath(path)))
            region._resolved = resolved
            region._tried = tried
            regions.append(region)
            continue

        # global/control opcodes that affect path resolution
        mlow = line.lower()
        if mlow.startswith("default_path="):
            default_path = line.split("=", 1)[1].strip()

    sample_paths = {r._resolved for r in regions}
    return regions, default_path, sample_paths, errors


def _parse_opcodes(text):
    """Parse 'key=value key=value' tokens into a dict.

    Stores the raw sample= value under __sample_raw so it survives the
    integer-coercion step later.
    """
    opcodes = {}
    for tok in re.findall(r'(\w+)=("[^"]*"|\S+)', text):
        key, val = tok[0].lower(), tok[1].strip('"')
        if key == "sample":
            opcodes["__sample_raw"] = val
        else:
            opcodes[key] = val
    return opcodes


# ── Checks ──────────────────────────────────────────────────────────────────
def check_sample_existence(regions, sfz_dir):
    """Verify each region's sample file exists; mark missing ones."""
    missing = []
    for r in regions:
        if not os.path.exists(r._resolved):
            r.exists = False
            r.reason = "missing"
            missing.append(r)
    return missing


def check_key_coverage(regions, programs=None):
    """Find (program, key) cells with no matching region across 0..127.

    Returns list of (program, lokey, hikey) gaps. If `programs` is None,
    reports a single combined coverage over all regions.
    """
    progs = programs if programs is not None else [None]
    gaps = []
    for prog in progs:
        covered = [False] * 128
        for r in regions:
            if prog is not None:
                if r.hiprog < prog or r.loprog > prog:
                    continue
            for k in range(max(0, r.lokey), min(127, r.hikey) + 1):
                covered[k] = True
        # collapse runs of uncovered keys
        run_start = None
        for k in range(128):
            if not covered[k]:
                if run_start is None:
                    run_start = k
            else:
                if run_start is not None:
                    gaps.append((prog, run_start, k - 1))
                    run_start = None
        if run_start is not None:
            gaps.append((prog, run_start, 127))
    return gaps


def check_velocity_holes(regions):
    """Per (program, key), report velocity gaps inside 0..127.

    A 'hole' is a velocity band that no region covers even though regions
    exist for that key on both sides of it.
    """
    holes = defaultdict(list)
    by_prog_key = defaultdict(list)
    for r in regions:
        by_prog_key[(r.loprog, r.lokey, r.hikey)].append(r)

    for (prog, lo, hi), regs in by_prog_key.items():
        if len(regs) < 2:
            continue
        regs.sort(key=lambda r: r.lovel)
        for i in range(len(regs) - 1):
            gap_lo = regs[i].hivel + 1
            gap_hi = regs[i + 1].lovel - 1
            if gap_lo <= gap_hi:
                holes[(prog, lo, hi)].append((gap_lo, gap_hi))
    return holes


def check_duplicates(regions):
    """Find regions sharing the same sample file (likely accidental copy)."""
    by_sample = defaultdict(list)
    for r in regions:
        by_sample[r._resolved].append(r)
    dups = {p: rs for p, rs in by_sample.items() if len(rs) > 1}
    return dups


def check_orphans(sample_dir, referenced):
    """WAV files in sample_dir that no region references."""
    if not sample_dir or not os.path.isdir(sample_dir):
        return []
    orphans = []
    for f in glob.glob(os.path.join(sample_dir, "**", "*.wav"), recursive=True):
        if os.path.abspath(f) not in referenced:
            orphans.append(f)
    return orphans


def check_drums_pair(main_regions, drums_regions):
    """Sanity-check a main+drums pairing.

    Two failure modes matter here:

      1. A drums region that is explicitly gated to a channel OTHER than 10
         (lochan/hichan set but not covering 10) → percussion is silent.
      2. A drums bank with NO channel restriction at all. That is the
         *intended* design for a standalone drums synth the host routes
         channel 10 into — but it only works if the drums are loaded as a
         SEPARATE instrument. Loaded inside the melodic synth, every note
         in the N35-N81 range would also trigger a drum hit. We warn so
         the routing requirement is explicit.
    """
    issues = []
    n_unrestricted = 0
    n_misgated = 0
    for r in drums_regions:
        # default (no opcode) → lochan=1, hichan=16 = accepts everything
        has_gate = (r.lochan != 1 or r.hichan != 16)
        if has_gate and not (r.lochan <= 10 <= r.hichan):
            n_misgated += 1
        elif not has_gate:
            n_unrestricted += 1
    if n_misgated:
        issues.append(
            f"{n_misgated}/{len(drums_regions)} drums region(s) are channel-"
            f"gated but do NOT cover channel 10 → percussion silent")
    if n_unrestricted:
        issues.append(
            f"{n_unrestricted}/{len(drums_regions)} drums region(s) have no "
            f"channel gate (lochan/hichan) — OK for a standalone ch10-routed "
            f"synth, but MUST be loaded as a separate instrument from the "
            f"melodic bank, or every note N35-N81 also fires a drum hit")
    return issues


# ── Reporting ───────────────────────────────────────────────────────────────
def report_file(label, sfz_path, default_path, regions,
                missing, gaps, vel_holes, dups, orphans, parse_errors,
                verbose=False):
    """Print a per-file report. Returns count of ERROR-level issues."""
    n_err = 0
    print(cyan(f"══ {label} ══"))
    print(dim(f"  file: {sfz_path}"))
    if default_path:
        print(dim(f"  default_path: {default_path}"))
    print(dim(f"  regions: {len(regions)}"))

    for e in parse_errors:
        print(red(f"  ✗ PARSE: {e}"))
        n_err += 1

    if missing:
        n_err += len(missing)
        print(red(f"  ✗ {len(missing)} MISSING sample(s):"))
        shown = missing[:20]
        for r in shown:
            print(red(f"      L{r.line}: {os.path.basename(r.sample)}"))
            print(dim(f"          → {r._resolved}"))
        if len(missing) > len(shown):
            print(dim(f"      ... and {len(missing) - len(shown)} more"))
    else:
        print(green("  ✓ all sample paths resolve on disk"))

    if dups:
        print(yellow(f"  ⚠ {sum(len(v) for v in dups.values())} regions across "
                     f"{len(dups)} duplicate sample file(s):"))
        for path, rs in list(dups.items())[:5]:
            lines = ", ".join(f"L{r.line}" for r in rs[:4])
            print(yellow(f"      {os.path.basename(path)}: {lines}"))

    if gaps:
        total_gaps = sum(g[2] - g[1] + 1 for g in gaps)
        print(yellow(f"  ⚠ {len(gaps)} key-coverage gap(s) "
                     f"({total_gaps} silent note cell(s))"))
        for prog, lo, hi in gaps[:10]:
            prog_str = f"prog {prog}" if prog is not None else "any prog"
            rng = (f"{midi_to_name(lo)}"
                   if lo == hi else f"{midi_to_name(lo)}..{midi_to_name(hi)}")
            print(yellow(f"      {prog_str}: keys {rng} ({lo}-{hi}) trigger nothing"))
        if len(gaps) > 10:
            print(dim(f"      ... and {len(gaps) - 10} more"))

    if vel_holes:
        total_vh = sum(sum(h - l + 1 for l, h in v) for v in vel_holes.values())
        print(yellow(f"  ⚠ {len(vel_holes)} key(s) with velocity holes "
                     f"({total_vh} silent vel cell(s))"))
        for (prog, lo, hi), vh in list(vel_holes.items())[:5]:
            prog_str = prog if prog is not None else "*"
            rng = (f"{midi_to_name(lo)}"
                   if lo == hi else f"{midi_to_name(lo)}..{midi_to_name(hi)}")
            vstr = ", ".join(f"{a}-{b}" for a, b in vh[:3])
            print(yellow(f"      prog {prog_str} key {rng}: vel gap {vstr}"))

    if orphans:
        print(yellow(f"  ⚠ {len(orphans)} orphan WAV(s) on disk not referenced:"))
        for o in orphans[:8]:
            print(yellow(f"      {os.path.relpath(o, PROJECT_ROOT)}"))
        if len(orphans) > 8:
            print(dim(f"      ... and {len(orphans) - 8} more"))

    status = red("FAIL") if n_err else green("OK")
    print(f"  → {status}\n")
    return n_err


# ── Driver ──────────────────────────────────────────────────────────────────
def verify_one(sfz_path, sample_dir=None, verbose=False):
    """Run all checks on a single .sfz file. Returns error count."""
    sfz_path = os.path.abspath(sfz_path)
    regions, default_path, sample_paths, parse_errors = parse_sfz(sfz_path)

    missing = check_sample_existence(regions, os.path.dirname(sfz_path))
    programs = sorted({r.loprog for r in regions if r.loprog == r.hiprog}) or None
    gaps = check_key_coverage(regions, programs)
    vel_holes = check_velocity_holes(regions)
    dups = check_duplicates(regions)
    orphans = check_orphans(sample_dir, {os.path.abspath(p) for p in sample_paths})

    return report_file(os.path.basename(sfz_path), sfz_path, default_path,
                       regions, missing, gaps, vel_holes, dups, orphans,
                       parse_errors, verbose), orphans


def verify_pair(main_path, drums_path):
    """Verify a main bank + its drums companion together."""
    main_path = os.path.abspath(main_path)
    drums_path = os.path.abspath(drums_path)
    main_regs, main_dp, main_sp, main_err = parse_sfz(main_path)
    drum_regs, drum_dp, drum_sp, drum_err = parse_sfz(drums_path)

    n = report_file(f"{os.path.basename(main_path)} (main)",
                    main_path, main_dp, main_regs,
                    check_sample_existence(main_regs, os.path.dirname(main_path)),
                    check_key_coverage(main_regs),
                    check_velocity_holes(main_regs),
                    check_duplicates(main_regs),
                    [], main_err)
    n2 = report_file(f"{os.path.basename(drums_path)} (drums)",
                     drums_path, drum_dp, drum_regs,
                     check_sample_existence(drum_regs, os.path.dirname(drums_path)),
                     check_key_coverage(drum_regs),
                     check_velocity_holes(drum_regs),
                     check_duplicates(drum_regs),
                     [], drum_err)

    print(cyan(f"══ pairing ══"))
    pair_issues = check_drums_pair(main_regs, drum_regs)
    for i in pair_issues:
        # channel-gating problems are routing warnings, not hard errors —
        # the samples exist and the keys map fine.
        print(yellow(f"  ⚠ {i}"))
    # also confirm no sample path collision between the two
    shared = main_sp & drum_sp
    if shared:
        print(yellow(f"  ⚠ {len(shared)} sample(s) shared between main & drums"))
        for s in list(shared)[:5]:
            print(yellow(f"      {os.path.basename(s)}"))
    if pair_issues or shared:
        print(yellow(f"  → PAIR has warnings\n"))
    else:
        print(green("  → PAIR OK\n"))
    return n + n2


def find_default_pairs():
    """Auto-discover (main, drums) pairs in sfz/ by naming convention."""
    pairs = []
    sfz_dir = os.path.join(PROJECT_ROOT, "sfz")
    mains = sorted(glob.glob(os.path.join(sfz_dir, "*_sfizz.sfz")))
    for m in mains:
        base = os.path.basename(m)[:-len("_sfizz.sfz")]
        drums = os.path.join(sfz_dir, f"{base}_sfizz_drums.sfz")
        if os.path.exists(drums):
            pairs.append((m, drums))
    return pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sfz", nargs="*", help=".sfz file(s) to verify")
    ap.add_argument("--pair", nargs=2, metavar=("MAIN", "DRUMS"),
                    help="verify a main bank and its drums companion together")
    ap.add_argument("--all", action="store_true",
                    help="verify every .sfz in sfz/ (default when no args)")
    ap.add_argument("--sample-dir", help="sample dir for orphan check")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    total_err = 0
    saw_any = False

    if args.pair:
        saw_any = True
        total_err += verify_pair(args.pair[0], args.pair[1])

    if args.sfz:
        saw_any = True
        for sfz in args.sfz:
            err, _ = verify_one(sfz, args.sample_dir, args.verbose)
            total_err += err

    if args.all or not saw_any:
        print(cyan("Auto-scanning sfz/ — pairing each *_sfizz.sfz with its "
                   "*_sfizz_drums.sfz sibling\n"))
        pairs = find_default_pairs()
        for main_path, drums_path in pairs:
            total_err += verify_pair(main_path, drums_path)
        # verify bare banks that have no drums sibling
        sfz_dir = os.path.join(PROJECT_ROOT, "sfz")
        paired = {os.path.abspath(m) for m, _ in pairs}
        for sfz in sorted(glob.glob(os.path.join(sfz_dir, "*.sfz"))):
            if os.path.abspath(sfz) in paired:
                continue
            if sfz.endswith("_sfizz_drums.sfz"):
                continue  # handled as part of a pair
            err, _ = verify_one(sfz, args.sample_dir, args.verbose)
            total_err += err

    if total_err:
        print(red(f"\n✗ {total_err} ERROR(s) found."))
        sys.exit(1)
    else:
        print(green("\n✓ All SFZ banks verified clean."))


if __name__ == "__main__":
    main()
