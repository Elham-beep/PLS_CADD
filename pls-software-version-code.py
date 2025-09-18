#!/usr/bin/env python3
"""
High-level purpose

A Tkinter desktop app that:
Takes designer inputs for a pole with triangular cross-arms (heights and half-arm lengths).
Reads a template .POL file (PLS-CADD format).
Patches only the exact numeric places that matter (robustly, no “two lines below” brittle logic).
Optionally updates external libraries (.cpp for mast lengths, .xrm for crossarms).
Writes the finished .POL and an optional stick-model .DXF (if ezdxf is installed).
Main data model and terms

EW1: Above-ground mast height.
UG: Underground (foundation) depth.
CA1, CA2, CA3: Heights for the top/middle/bottom cross-arm.
CA?_1p / CA?_1x: Positive- and negative-side half-arm lengths (X coordinate offsets). Convention: positive = right (R), negative = left (L).
CA2_2p, CA2_3p: Additional insulator positions for the middle cross-arm (positive side only).
Libraries: .cpp holds mast lengths, .xrm holds cross-arm definitions. The app can ensure required entries exist.

Author:Elham 30-Jul-2025

"""
                                                                                     
from __future__ import annotations
import pathlib
import re
import tkinter as tk
import sys
from tkinter import filedialog, messagebox
from typing import Dict, List, Tuple

# DEBUG: Boolean toggle for debug prints. dprint(...) prints only when DEBUG = True.
DEBUG = True
def dprint(*a, **k):
    if DEBUG:
        print(*a, **k)
# ─────────────────────────── settings ──────────────────────────────────────
 # app_root(): Resolves the application root, compatible with PyInstaller (sys._MEIPASS) or the script’s folder.
def app_root() -> pathlib.Path:
    # When frozen by PyInstaller, sys._MEIPASS points to the temp dir
    if getattr(sys, 'frozen', False):
        return pathlib.Path(sys._MEIPASS)
    # Otherwise, use the script folder
    return pathlib.Path(__file__).resolve().parent


TEMPLATE_PATH = app_root() / "assets" / "Prueba n46 original-triangular-arm - Copy.pol"

if not TEMPLATE_PATH.exists():
    from tkinter import messagebox
    messagebox.showerror("Template missing", f"Template not found:\n{TEMPLATE_PATH}")
    sys.exit(1)

#Number of decimal places when writing floats back into the .POL.
DECIMALS      = 2

#XRM_TEMPLATE / CROSSARM_ROW: String templates of cross-arm library rows used in .xrm and the injected .POL crossarm block.
XRM_TEMPLATE = (
    "'CROSSARM-{L}' 'ACC-200' 1         0.06      0.00125      7.2e-05"
    "          900          0.3{L:>11}{spacer}1 "
    "210000000000      3000000      3000000      3000000"
    "            0            0            0          0.2 0 0"
)

# Accepted input tags per arm (positive/negative sides). Useful to validate or constrain user input set.
ARM_TAGS: dict[str, list[str]] = {
    "CA1": ["CA1_1p", "CA1_1x"],
    "CA2": ["CA2_1p", "CA2_1x", "CA2_2p", "CA2_3p"],
    "CA3": ["CA3_1p", "CA3_1x"],
}



#The ordered list of GUI input fields that will be rendered and collected.
FIELDS = (
    "EW1",
    "UG",
    "CA1", "CA1_1p", "CA1_1x", 
    "CA2", "CA2_1p", "CA2_1x", "CA2_2p", "CA2_3p",
    "CA3", "CA3_1p", "CA3_1x",
)

LIB_TEMPLATE = (
    "{key} '' '180' 1 5"
    "{tot:>12.1f}{ug:>13.1f}"
    "          0.6          0.4            0"
    "       0.1397       0.1143          0.9"
    "  41368000000  13789000000        26635"
    "            0            0            0"
    "            0            0            0            0        0 ; # Capacities"
)



def needed_crossarm_lengths(v: dict[str, float]) -> set[float]:
    # Returns set of unique positive, non-zero half-arm lengths required.
    tags = [
        "CA1_1p", "CA1_1x",
        "CA2_1p", "CA2_1x", "CA2_2p", "CA2_3p",
        "CA3_1p", "CA3_1x",
    ]
    return {abs(v[t]) for t in tags if abs(v[t]) > 0}

# ──────────────────── mast-length library (.cpp) ─────────────────────────
def update_cpp_library(lib_path: pathlib.Path, v: dict[str, float]) -> None:
    """
    Ensures mast length entry exists for key 'C-{EW1:.1f}' with total length = EW1 + UG.
    Appends LIB_TEMPLATE row if not present, else informs user it’s already present.
    Shows success/error dialogs; re-raises on error so caller can abort workflow.
    """
    try:
        key       = f"'C-{v['EW1']:.1f}'"
        lines     = lib_path.read_text(encoding="utf-8").splitlines()
        if any(ln.lstrip().startswith(key) for ln in lines):
            messagebox.showinfo(
                "Mast library",
                f"{lib_path.name}: entry {key} already present – nothing added."
            )
            return

        total_len = v['EW1'] + v['UG']
        new_line  = LIB_TEMPLATE.format(key=key, tot=total_len, ug=v['UG'])
        lines.append(new_line)
        lib_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        messagebox.showinfo(
            "Mast library",
            f"Added {key} to {lib_path.name}"
        )

    except Exception as exc:
        messagebox.showerror(
            "Mast library – update failed",
            f"Could not update {lib_path.name}:\n{exc}"
        )
        raise                       # propagate so caller can stop further work



# Button callback wrapper that asks for .cpp file and calls update_cpp_library() for the current GUI values.

def modify_library() -> None:
    """
    Ask user for the .cpp file and update it for the CURRENT GUI inputs.
    (Called by the ‘Modify library’ button.)
    """
    v = collect_values()
    if v is None:
        return                                  # invalid / missing numbers

    cpp_path = filedialog.askopenfilename(
        title="Select the mast-length library (.cpp)",
        filetypes=[("Library .cpp", "*.cpp"), ("All files", "*.*")]
    )
    if cpp_path:
        update_cpp_library(pathlib.Path(cpp_path), v)


# ───────────────── combined helper (cpp + xrm) ──────────────────────────
def update_libraries(v: dict[str, float]) -> None:
    """
    Update BOTH the .cpp (mast lengths) and .xrm (cross-arms) libraries
    required by the current GUI inputs *v*.
    Call this at the start of generate_pol() or from a dedicated button.
    """
    # 1)  .cpp
    cpp_path = filedialog.askopenfilename(
        title="Select the mast-length library (.cpp)",
        filetypes=[("Library .cpp", "*.cpp"), ("All files", "*.*")]
    )
    if cpp_path:
        update_cpp_library(pathlib.Path(cpp_path), v)

    # 2)  .xrm
    xrm_path = filedialog.askopenfilename(
        title="Select the cross-arm library (.xrm)",
        filetypes=[("Cross-arm library", "*.xrm"), ("All files", "*.*")]
    )
    if xrm_path:
        need = needed_crossarm_lengths(v)        # ← ignores any 0-length arms
        modify_xrm_library(pathlib.Path(xrm_path), need)
        
XRM_TAG_RE = re.compile(r"^'CROSSARM-([0-9.]+)'") #Detects lines beginning with 'CROSSARM-{L}' to learn which lengths are already present.
XRM_TEMPLATE = (
    "'CROSSARM-{L}' 'ACC-200' 1         0.06      0.00125      7.2e-05"
    "          900          0.3{L:>11}{spacer}1 "
    "210000000000      3000000      3000000      3000000"
    "            0            0            0          0.2 0 0"
)


def modify_xrm_library(xrm_path: pathlib.Path, required: set[float]) -> None:
    """
    Ensure *xrm_path* contains every length in *required*.
    Shows a popup on success or error; re-raises on error.
    Collects present lengths by parsing tags with XRM_TAG_RE.
    Computes missing lengths = required - present.
    """
    try:
        lines = xrm_path.read_text(encoding="utf-8").splitlines()
        present = {
            float(m.group(1))
            for ln in lines
            if (m := XRM_TAG_RE.match(ln.strip()))
        }

        missing = sorted(required - present)
        if not missing:
            messagebox.showinfo(
                "Cross-arm library",
                f"{xrm_path.name}: all required lengths already present."
            )
            return

        # for L in missing:
        #     lines.extend([_make_xrm_line(L), "0"])

        xrm_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        messagebox.showinfo(
            "Cross-arm library",
            f"Added {', '.join(map(str, missing))} m arms to {xrm_path.name}"
        )

    except Exception as exc:
        messagebox.showerror(
            "Cross-arm library – update failed",
            f"Could not update {xrm_path.name}:\n{exc}"
        )
        raise



# every joint label that must be updated → (X-tag, Z-tag) coming from GUI
#"CA3-1" → X from "CA3_1p", Z from "CA3"
#"CA2-1" → X from "CA2_comb_pos" (derived = CA2_1p), Z from "CA2"
JOINT_MAP: Dict[str, Tuple[str, str]] = {
    "CA3-1": ("CA3_1p",      "CA3"),
    "CA2-1": ("CA2_comb_pos","CA2"),
    "CA2-2": ("CA2_2p",      "CA2"),
    "CA2-3": ("CA2_3p",      "CA2"),
    "CA1-1": ("CA1_1p",      "CA1"),
}

#Defines the order of eight “0 x z” rows that should appear in the unique reference block.
REF_ORDER: List[Tuple[str, str]] = [
    ("CA3_1p",          "CA3"),
    ("CA2_comb_pos",    "CA2"),
    ("CA2_2p",          "CA2"),
    ("CA2_3p",          "CA2"),
    ("CA1_1p",          "CA1"),
    ("CA3_1x",          "CA3"),
    ("CA2_comb_neg",    "CA2"),
    ("CA1_1x",          "CA1"),
]

FLOAT = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?" #Matches integer/float/exp numbers.
XYZ_RE = re.compile(rf"^\s*{FLOAT}\s+{FLOAT}\s+{FLOAT}(?:\s+{FLOAT})?$") #Matches lines with 3 or 4 float tokens (x y z [r]).

# ─────────────────────────── GUI setup ─────────────────────────────────────
root = tk.Tk()
root.title("PLS-CADD .POL generator")

ent: dict[str, tk.Entry] = {}
for row, tag in enumerate(FIELDS):
    tk.Label(root, text=f"{tag}:", anchor="w").grid(row=row, column=0, sticky="w",
                                                    padx=6, pady=3)
    e = tk.Entry(root, width=12)
    e.grid(row=row, column=1, padx=6, pady=3)
    ent[tag] = e

# ───────────────────────── helper utilities ────────────────────────────────
#Formats a float using DECIMALS decimals. Keeps numeric format consistent in output.
def fmt(num: float) -> str:
    """Uniform float formatting for writing back to the .POL file."""
    return f"{num:.{DECIMALS}f}"


def collect_values() -> dict[str, float] | None:
    '''Reads text from every Entry, casts to float. If any non-numeric, shows error and returns None. It also computes two derived fields:
    CA2_comb_pos = CA2_1p
    CA2_comb_neg = CA2_1x
    These are convenience aliases used in mapping and reference blocks.
'''
    vals: dict[str, float] = {}
    try:
        for tag, widget in ent.items():
            vals[tag] = float(widget.get())
    except ValueError:
        messagebox.showerror("Input error", "Every box needs a numeric value.")
        return None

    # derived fields
    vals["CA2_comb_pos"] =  vals["CA2_1p"]
    vals["CA2_comb_neg"] = vals["CA2_1x"]
    return vals

# ───────────────────────── pattern finders ─────────────────────────────────

def _find_joint_blocks(lines: List[str]) -> Dict[str, int]:
    '''
    Scans the template for joint records. Each record starts with a label line like 'CA3-1' and somewhere 
    in the next few lines there’s a numeric line “x y z [r]” (matched by XYZ_RE). 
    The function returns a map { 'label': numeric_line_index }.
    '''
    blocks: Dict[str, int] = {}
    i = 0
    while i < len(lines) - 2:
        m = re.match(r"^'([^']+)'", lines[i].strip())
        if m:
            label = m.group(1)
            # search ahead up to 5 lines for the numeric XYZ line
            for j in range(i + 1, min(i + 6, len(lines))):
                if XYZ_RE.match(lines[j]):
                    blocks[label] = j
                    break
            i = j
        else:
            i += 1
    return blocks

def _find_reference_block(lines: List[str]) -> int:
    """Searches for the first occurrence of 8 consecutive rows matching “0 x z” (no Y; specifically 0 at first column).
        For each of the 8 rows, sets X = v[x_tag], Z = v[z_tag], preserving “0” as the first token."""
    pat = re.compile(r"^\s*0\s+" + FLOAT + r"\s+" + FLOAT + r"\s*$")
    for i in range(len(lines) - 7):
        if all(pat.match(lines[i + k]) for k in range(8)):
            return i
    raise ValueError("Reference-coordinate block not found (expect 8 rows of '0 x z').")


# ───────────────────────── attachment patcher ────────────────────────────
ATTACH_RE = re.compile(
    r"""
    ^(?P<prefix>INL_ A(?P<arm>[123]) -)      #  INL_A2-
    (?P<side>[LR])                           #  L or R
    (?P<rest> - \d\.\d .*? )                 #  -2.2 … rest of the label
    (?P<num>\s+[-+]?\d+(?:\.\d+)?)           #  the X coordinate field
    \b
    """,
    re.VERBOSE,
)
# ─────────── combined helper ─────────────────────────────────────────


def patch_attachments(lines: List[str]) -> None:
    """
    Scans for lines like INL_A2-L-2.2 … followed by numeric columns.
    If the parsed X coordinate is negative, the side should be “L” (left), otherwise “R” (right).
    If mismatch, rebuilds the label with the corrected L/R.
    """
    for i, ln in enumerate(lines):
        m = ATTACH_RE.match(ln.strip())
        if not m:
            continue

        side  = m.group("side")
        x_val = float(m.group("num").split()[0])   # until first space

        correct_side = "L" if x_val < 0 else "R"
        if side == correct_side:
            continue                               # already consistent

        # rebuild the line with the corrected side
        new_label = f"{m.group('prefix')}{correct_side}{m.group('rest')}"
        lines[i] = new_label + ln[len(m.group(0)):]  # keep trailing cols

# ───────────────────────── template patcher ────────────────────────────────
ZERO_ZERO_RE   = re.compile(r"^\s*0\s+0\s+0\s*$") #Matches exactly “0 0 0” (possibly with spaces).
THREE_FLOAT_RE = re.compile(rf"^\s*{FLOAT}\s+{FLOAT}\s+{FLOAT}") #Matches three floats at start of line (not directly used in the final patch sequence).


# Regex that matches “firstA”, “secondA”, “thirdA”, “midA”, “midB”, “beamNo”, “HA..HG”.
_PLACE_RE = re.compile(r"\b(firstA|secondA|thirdA|midA|midB|beamNo|HA|HB|HC|HD|H0|HG)\b")


def _swap_placeholders(lines: list[str], v: dict[str, float]) -> None:
    """
    Replaces placeholders inline in the template with numeric text derived from v (the collected values).
    Mapping:
    firstA = |CA1_1p| (top outer positive half-arm length)
    secondA = |CA2_1p| (middle outer positive)
    thirdA = |CA3_1p| (bottom outer positive)
    midA = |CA2_2p| (middle arm right-side additional length)
    midB = |CA2_3p| (middle arm left-side additional length)
    beamNo = number of distinct half-arm lengths among the outer left/right halves (CA1_1p/x, CA2_1p/x, CA3_1p/x) that are non-zero
    HA/HB/HC = heights of CA1/CA2/CA3
    HD = EW1, H0 = UG, HG = EW1 + UG
    """

    repl = {
        # outer half-arm lengths ─ top → bottom
        "firstA":  f"{abs(v['CA1_1p']):g}",   # CA1 (top)
        "secondA": f"{abs(v['CA2_1p']):g}",   # CA2 (middle)
        "thirdA":  f"{abs(v['CA3_1p']):g}",   # CA3 (bottom)

        "midA":    f"{abs(v['CA2_2p']):g}",
        "midB":    f"{abs(v['CA2_3p']):g}",

        "beamNo":  str(len({abs(v[t]) for t in (
                            'CA1_1p','CA1_1x',
                            'CA2_1p','CA2_1x',
                            'CA3_1p','CA3_1x')
                            if v[t] != 0})),

        # height tokens (already top→bottom via HA/HB/HC)
        "HA": f"{v['CA1']:g}",   # top-arm height
        "HB": f"{v['CA2']:g}",   # middle-arm height
        "HC": f"{v['CA3']:g}",   # bottom-arm height
        "HD": f"{v['EW1']:g}",
        "H0": f"{v['UG']:g}",
        "HG": f"{v['EW1'] + v['UG']:g}",
    }
    dprint("DEBUG mapping:", {k: repl[k] for k in ("firstA","secondA","thirdA")})


    def _sub(m: re.Match) -> str:
        return repl[m.group(1)]

    for i, ln in enumerate(lines):
        if _PLACE_RE.search(ln):
            dprint("DEBUG placeholder line:", i, repr(ln))
            lines[i] = _PLACE_RE.sub(_sub, ln)


# ─────────────── cross-arm (half-arm) block injector ─────────────────
CROSSARM_ROW = (
    "'CROSSARM-{L}' 'ACC-200' 1         0.06      0.00125      7.2e-05"
    "          900          0.3{pad}{L}            1 "
    "210000000000      3000000      3000000      3000000"
    "            0            0            0          0.2 0 0"
)

_CA_PLACEHOLDER_RE = re.compile(r"'CROSSARM-(firstA|secondA|thirdA)'")

def _inject_crossarm_block(lines: list[str], v: dict[str, float]) -> None:
    """
    Finds the dummy block that contains placeholder rows 'CROSSARM-firstA|secondA|thirdA' followed by 0 lines.
    Deletes that dummy block.
    Builds a deduplicated sorted list of unique non-zero half-arm lengths used anywhere:
    CA3_1p/x, CA2_1p/x, CA2_2p, CA2_3p, CA1_1p/x
    Inserts one CROSSARM_ROW (with precise padding to keep columns) per length, each followed by a “0” line.
    """
    # unique half-arm lengths (metres)
    lengths = sorted({
        abs(v[tag])
        for tag in (
            "CA3_1p", "CA3_1x",
            "CA2_1p", "CA2_1x", "CA2_2p", "CA2_3p",
            "CA1_1p", "CA1_1x",
        )
        if v[tag] != 0
    })
    if not lengths:
        return

    # locate dummy block
    start = next(
        (i for i, ln in enumerate(lines) if _CA_PLACEHOLDER_RE.search(ln)),
        None
    )
    if start is None:
        return                                  # template missing block

    # remove dummy rows ('CROSSARM-*' + trailing 0s)
    end = start
    while end < len(lines) and (
        _CA_PLACEHOLDER_RE.search(lines[end]) or lines[end].strip() == "0"
    ):
        end += 1
    del lines[start:end]

    # build new rows
    new_rows: list[str] = []
    for L in lengths:
        pad = " " * (12 - len(f"{L:g}"))        # keep column width
        new_rows.append(CROSSARM_ROW.format(L=f"{L:g}", pad=pad))
        new_rows.append("0")

    lines[start:start] = new_rows
FLOAT = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"




def patch_pol(template: pathlib.Path, dest: pathlib.Path,
              v: Dict[str, float]) -> None:
    """
    Patch four areas inside *template* and write the result to *dest*:

        1. joint-geometry records               
        2. 8-row reference-coordinate block     
        3. the descending “0 0 z …” block       (overwrite only main heights)
        4. the single “EW1  UG  0 … flags …”    (first two numbers only)
    """
    lines = template.read_text(encoding="utf-8").splitlines()

    # replace firstA / secondA / thirdA / midA / midB / beamNo everywhere
    _swap_placeholders(lines, v)

    # ── 1️⃣ joint-geometry lines ──────────────────────────────────────────
    joint_xyz = _find_joint_blocks(lines)
    for label, (x_tag, z_tag) in JOINT_MAP.items():
        if v[x_tag] == 0:                       # If the half-arm length = 0, skip (arm absent).
            continue
        #Else, split the numeric line, update X (index 1) using v[x_tag] and Z (index 2) using v[z_tag], write back.
        idx   = joint_xyz[label]
        parts = lines[idx].split()
        parts[1] = fmt(v[x_tag])                # X
        parts[2] = fmt(v[z_tag])                # Z
        lines[idx] = " ".join(parts)

    # ── 2️⃣ 8-row reference block ─────────────────────────────────────────
    ref_start = _find_reference_block(lines)
    for k, (x_tag, z_tag) in enumerate(REF_ORDER):
        parts = lines[ref_start + k].split()
        parts[1] = fmt(v[x_tag])
        parts[2] = fmt(v[z_tag])
        lines[ref_start + k] = " ".join(parts)

    # ── 3️⃣ “0 0 z …” descending-height block ────────────────────────────
    '''After joint geometry, finds a “0 0 0” marker (ZERO_ZERO_RE) and then updates the next few lines’ Z to overwrite the main heights only.
    The plan is:
    line +1 becomes EW1 (HD),
    +2 becomes CA1 (HA),
    +3 becomes CA2 (HB),
    +4 becomes CA3 (HC).
    Each line must begin with “0 0” and have at least 3 tokens. If not, it skips that line to avoid corrupting unexpected templates.'''
    search_start = max(joint_xyz.values()) + 1        # first line past joints
    try:
        zz0 = next(i for i in range(search_start, len(lines))
                   if ZERO_ZERO_RE.match(lines[i]))
    except StopIteration:
        raise ValueError("'0 0 0' marker not found in template .POL")
    plan = [
        (1, "EW1"),   # HD
        (2, "CA1"),   # HA
        (3, "CA2"),   # HB
        (4, "CA3"),   # HC
    ]

    for off, tag in plan:
        tgt = zz0 + off
        if tgt >= len(lines) or v[tag] == 0:
            continue
        parts = lines[tgt].split()
        if len(parts) < 3 or parts[0] != "0" or parts[1] != "0":
            continue                            # template unexpectedly different
        parts[2] = fmt(v[tag])
        lines[tgt] = " ".join(parts)



    # ── 6️⃣ inject real CROSSARM rows, no duplicates ─────────────────────
    _inject_crossarm_block(lines, v)


    # ── 7️⃣ write result ────────────────────────────────────────────────
    #Writes the patched content to dest as UTF-8.
    dest.write_text("\n".join(lines), encoding="utf-8")

    
    
    # ───────────────────────── DXF export helper ───────────────────────────────
#
# Requires the pure-Python "ezdxf" library (pip install ezdxf).
# The DXF is a *stick* model meant for quick visual checks in Autodesk Viewer,
# FreeCAD, etc.  One layer per element so you can recolour / hide freely.

try:
    import ezdxf
except ModuleNotFoundError:
    ezdxf = None    # we'll warn the user if they ask for a DXF
                    # but don't have the package installed


def _build_geometry_from_values(v: Dict[str, float]) -> List[Tuple[Tuple[float, float, float],
                                                                    Tuple[float, float, float],
                                                                    str]]:
    """
    Return a list of (p1, p2, layer_name) 3-D segments that make up the pole:
        • vertical shaft  (layer "POLE")
        • three cross-arms (layers "CA1", "CA2", "CA3")
    """
    geom: List[Tuple[Tuple[float, float, float],
                     Tuple[float, float, float],
                     str]] = []

    # vertical shaft: ground (Z = 0) → EW1
    geom.append(((0, 0, 0), (0, 0, v["EW1"]), "POLE"))

    # cross-arms (Y is zero for every point; X ±, Z at CA? height)
    arms = (
        ("CA1", "CA1_1x", "CA1_1p"),
        ("CA2", "CA2_1x", "CA2_1p"),   # only the outer arm – CA2_2p/3p are insulator points
        ("CA3", "CA3_1x", "CA3_1p"),
    )
    for z_tag, x_neg_tag, x_pos_tag in arms:
        z = v[z_tag]
        geom.append(((v[x_neg_tag], 0, z), (v[x_pos_tag], 0, z), z_tag))  # layer == z_tag

    return geom


def write_dxf_from_values(v: Dict[str, float], dxf_path: pathlib.Path) -> None:
    """Build and write the DXF stick model."""
    if ezdxf is None:
        raise RuntimeError(
            "DXF export requested but the ezdxf package is not installed. "
            "Run  →  pip install ezdxf  ← and try again."
        )

    doc = ezdxf.new(setup=True)
    msp = doc.modelspace()

    for p1, p2, layer in _build_geometry_from_values(v):
        if layer not in doc.layers:
            doc.layers.add(name=layer)
        msp.add_line(p1, p2, dxfattribs={"layer": layer})

    # add tiny circles at joint labels for visibility
    for label, (x_tag, z_tag) in {
        "CA1-1": ("CA1_1p", "CA1"),
        "CA2-1": ("CA2_1p", "CA2"),
        "CA2-2": ("CA2_2p", "CA2"),
        "CA2-3": ("CA2_3p", "CA2"),
        "CA3-1": ("CA3_1p", "CA3"),
    }.items():
        x, z = v[x_tag], v[z_tag]
        msp.add_circle((x, 0, z), radius=0.05,
                       dxfattribs={"layer": "JOINTS"})

        txt = msp.add_text(label,
                           dxfattribs={"height": 0.15,
                                       "layer": "JOINTS"})
        try:                                 # ezdxf ≥ 0.18
            txt.set_pos((x, 0, z), align="LEFT")
        except AttributeError:               # ezdxf ≤ 0.17
            txt.dxf.insert = (x, 0, z)


    doc.saveas(dxf_path)


def _build_geometry_from_values(v: dict[str, float]):
    geom = []
    # vertical shaft
    geom.append(((0, 0, 0), (0, 0, v["EW1"]), "POLE"))

    def add_if_nonzero(x1_tag, x2_tag, z_tag, layer_name):
        x1, x2, z = v[x1_tag], v[x2_tag], v[z_tag]
        if x1 != 0 or x2 != 0:             # at least one half-arm present
            geom.append(((x1, 0, z), (x2, 0, z), layer_name))

    add_if_nonzero("CA1_1x", "CA1_1p", "CA1", "CA1")
    add_if_nonzero("CA2_1x", "CA2_1p", "CA2", "CA2")
    add_if_nonzero("CA3_1x", "CA3_1p", "CA3", "CA3")
    return geom

# ───────────────────────── GUI callback ────────────────────────────────────
def generate_pol() -> None:
    """
    1. Read the values already in the GUI.
    2. Ask the user where to save the finished .POL (and .DXF).
    3. Patch the template and write the files.
    4.Attempts to write a .dxf next to it; warns only if ezdxf is missing.
    Shows “Done” dialog with file names.
    Note: This function no longer updates .cpp/.xrm. That’s separated to the “Modify libraries” button.

    """
    vals = collect_values()
    if vals is None:
        return                               # some box was empty / non-numeric

    # Let the user choose the target .POL
    dst_path = filedialog.asksaveasfilename(
        title="Save finished .POL (+ .DXF)",
        defaultextension=".pol",
        filetypes=[("PLS-CADD .POL", "*.pol"), ("All files", "*.*")],
        initialfile="tower.pol",
    )
    if not dst_path:
        return
    dst_path = pathlib.Path(dst_path)

    try:
        # ①  write the patched .POL
        patch_pol(TEMPLATE_PATH, dst_path, vals)

        # ②  optional DXF
        try:
            write_dxf_from_values(vals, dst_path.with_suffix(".dxf"))
        except RuntimeError as e:
            # ezdxf missing – warn but still succeed on .POL
            messagebox.showwarning("DXF not written", str(e))

    except Exception as exc:
        messagebox.showerror("Error while generating files", str(exc))
        return

    messagebox.showinfo(
        "Done",
        f"Wrote:\n{dst_path.name}\n"
        + (f"and {dst_path.with_suffix('.dxf').name}" if ezdxf else "")
    )



# ───────────────────────── run the GUI ─────────────────────────────────────
tk.Button(root, text="Generate .POL", command=generate_pol) \
  .grid(row=len(FIELDS), columnspan=2, pady=10)
  


tk.Button(root, text="Modify libraries",
          command=lambda: (vals := collect_values()) and vals
                          and update_libraries(vals)
).grid(row=len(FIELDS)+1, columnspan=2, pady=4)



root.mainloop()
