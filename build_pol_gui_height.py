#!/usr/bin/env python3
"""
Tkinter front-end that:
  • lets the designer key in cross-arm data
  • scans the template .POL for every joint-geometry line + the 8-row
    reference-coordinate block
  • patches only the numbers that matter (no “two lines below” guessing)
  • writes the finished .POL

Author:Elham 30-Jul-2025
in this version we are going to test mid cross arm sections
"""

from __future__ import annotations
import pathlib
import re
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Dict, List, Tuple

# ─────────────────────────── settings ──────────────────────────────────────
TEMPLATE_PATH = pathlib.Path("Prueba n46 original-height.pol")

DECIMALS      = 2

XRM_TEMPLATE = (
    "'CROSSARM-{L}' 'ACC-200' 1         0.06      0.00125      7.2e-05"
    "          900          0.3{L:>11}{spacer}1 "
    "210000000000      3000000      3000000      3000000"
    "            0            0            0          0.2 0 0"
)

# positive-side and negative-side tags we accept as user input
ARM_TAGS: dict[str, list[str]] = {
    "CA1": ["CA1_1p", "CA1_1x"],
    "CA2": ["CA2_1p", "CA2_1x", "CA2_2p", "CA2_3p"],
    "CA3": ["CA3_1p", "CA3_1x"],
}



# map GUI field → description / order
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
    """
    Return the set of UNIQUE *full* cross-arm lengths required by the
    current tower.  Tags whose value is 0 are ignored (meaning: “not fitted
    on this mast”).
    """
    lengths: set[float] = set()
    for tag_list in ARM_TAGS.values():
        for tag in tag_list:
            L = abs(v[tag])
            if L > 0:                       # 0 → arm not present
                lengths.add(L)
    return lengths



def needed_crossarm_lengths(v: dict[str, float]) -> set[float]:
    # returns unique positive full lengths; zero = “not present”
    tags = [
        "CA1_1p", "CA1_1x",
        "CA2_1p", "CA2_1x", "CA2_2p", "CA2_3p",
        "CA3_1p", "CA3_1x",
    ]
    return {abs(v[t]) for t in tags if abs(v[t]) > 0}

# ──────────────────── mast-length library (.cpp) ─────────────────────────
def update_cpp_library(lib_path: pathlib.Path, v: dict[str, float]) -> None:
    """
    Make sure *lib_path* contains an entry for the current EW1 + UG.
    On success a green info popup is shown; on failure a red error popup
    appears and the exception is re-raised so the caller can abort.
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



# zero-argument wrapper so the dedicated button still works
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
        
XRM_TAG_RE = re.compile(r"^'CROSSARM-([0-9.]+)'")
XRM_TEMPLATE = (
    "'CROSSARM-{L}' 'ACC-200' 1         0.06      0.00125      7.2e-05"
    "          900          0.3{L:>11}{spacer}1 "
    "210000000000      3000000      3000000      3000000"
    "            0            0            0          0.2 0 0"
)

def _make_xrm_line(length: float) -> str:
    return XRM_TEMPLATE.format(
        L=f"{length:g}",
        spacer=" " * (12 - len(f"{length:g}")),
    )

def modify_xrm_library(xrm_path: pathlib.Path, required: set[float]) -> None:
    """
    Ensure *xrm_path* contains every length in *required*.
    Shows a popup on success or error; re-raises on error.
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

        for L in missing:
            lines.extend([_make_xrm_line(L), "0"])

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
JOINT_MAP: Dict[str, Tuple[str, str]] = {
    "CA3-1": ("CA3_1p",      "CA3"),
    "CA2-1": ("CA2_comb_pos","CA2"),
    "CA2-2": ("CA2_2p",      "CA2"),
    "CA2-3": ("CA2_3p",      "CA2"),
    "CA1-1": ("CA1_1p",      "CA1"),
}

# order of the eight “0  x  z” rows in the reference block
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

FLOAT = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
XYZ_RE = re.compile(rf"^\s*{FLOAT}\s+{FLOAT}\s+{FLOAT}(?:\s+{FLOAT})?$")

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
def fmt(num: float) -> str:
    """Uniform float formatting for writing back to the .POL file."""
    return f"{num:.{DECIMALS}f}"

def collect_values() -> dict[str, float] | None:
    """Read and validate GUI entries; add the derived CA2 ± combos."""
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
    """
    Return {joint_label: index_of_XYZ_line}.  Robust to blank lines or
    minor re-ordering inside the 5-row joint record.
    """
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
    """Return the start index of the unique 8-row '0 x z' reference block."""
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
    Ensure every INL_A?-?-?.? label’s L/R side matches the sign of the X
    coordinate on the same line.
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

FLOAT          = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
XYZ_RE         = re.compile(rf"^\s*{FLOAT}\s+{FLOAT}\s+{FLOAT}(?:\s+{FLOAT})?$")
ZERO_ZERO_RE   = re.compile(r"^\s*0\s+0\s+0\s*$")
THREE_FLOAT_RE = re.compile(rf"^\s*{FLOAT}\s+{FLOAT}\s+{FLOAT}")
# helper near the other utilities
import re
_TOKEN_RE = re.compile(r"\b(firstA|secondA|thirdA|midA|midB|beamNo|HA|HB|HC|HD|H0|HG)\b")
# whole-word match of the   first   second   third  tokens
_PLACE_RE = re.compile(r"\b(firstA|secondA|thirdA|midA|midB|beamNo|HA|HB|HC|HD|H0|HG)\b")

import re

# matches the placeholder words even when embedded in other text
_PLACE_RE = re.compile(r"\b(firstA|secondA|thirdA|midA|midB|beamNo|HA|HB|HC|HD|H0|HG)\b")

def _swap_placeholders(lines: list[str], v: dict[str, float]) -> None:
    """
    Replace every occurrence of the substrings
        first, second, third, beamNo
    with the appropriate numeric text, without altering anything else.

        firstA  → |CA3_1p|      HA → |CA3|
        secondA → |CA2_1p|      HB → |CA2|
        thirdA  → |CA1_1p|      HC → |CA1|
        midA    → |CA2_2p|      HD → |EW1|
        midB    → |CA2_3p|      H0 → |UG|
        beamNo  → # DISTINCT half-arm lengths
        HG      → H0 + HD  (= UG + EW1)
    """
    # unique non-zero half-arms (metres)
    uniq = {abs(v[t]) for t in (
        "CA3_1p", "CA3_1x",
        "CA2_1p", "CA2_1x", "CA2_2p", "CA2_3p",
        "CA1_1p", "CA1_1x") if v[t] != 0}

    repl = {
        # existing tokens
        "firstA":  f"{abs(v['CA3_1p']):g}",
        "secondA": f"{abs(v['CA2_1p']):g}",
        "thirdA":  f"{abs(v['CA1_1p']):g}",
        "midA":    f"{abs(v['CA2_2p']):g}",
        "midB":    f"{abs(v['CA2_3p']):g}",
        "beamNo":  str(len(uniq)),

        # new height tokens
        "HA": f"{v['CA3']:g}",
        "HB": f"{v['CA2']:g}",
        "HC": f"{v['CA1']:g}",
        "HD": f"{v['EW1']:g}",
        "H0": f"{v['UG']:g}",
        "HG": f"{v['EW1'] + v['UG']:g}",
    }

    def _sub(m: re.Match) -> str:
        return repl[m.group(1)]

    for i, ln in enumerate(lines):
        if _PLACE_RE.search(ln):
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
    Delete the dummy block that starts with 'CROSSARM-first' and insert a
    real block that contains ONE row for each UNIQUE non-zero HALF-arm
    length used on the pole.  Each row is followed by a single '0' line.
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

def patch_pol(template: pathlib.Path, dest: pathlib.Path,
              v: Dict[str, float]) -> None:
    """
    Patch four areas inside *template* and write the result to *dest*:

        1. joint-geometry records               (unchanged logic)
        2. 8-row reference-coordinate block     (unchanged logic)
        3. the descending “0 0 z …” block       (overwrite only main heights)
        4. the single “EW1  UG  0 … flags …”    (first two numbers only)
    """
    lines = template.read_text(encoding="utf-8").splitlines()

    # replace firstA / secondA / thirdA / midA / midB / beamNo everywhere
    _swap_placeholders(lines, v)

    # ── 1️⃣ joint-geometry lines ──────────────────────────────────────────
    joint_xyz = _find_joint_blocks(lines)
    for label, (x_tag, z_tag) in JOINT_MAP.items():
        if v[x_tag] == 0:                       # half-arm absent
            continue
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
    # search for the 0-0-0 marker ONLY *after* the joint-geometry section
    search_start = max(joint_xyz.values()) + 1        # first line past joints
    try:
        zz0 = next(i for i in range(search_start, len(lines))
                   if ZERO_ZERO_RE.match(lines[i]))
    except StopIteration:
        raise ValueError("'0 0 0' marker not found in template .POL")

    plan = [                     # (offset from 0-0-0 row, GUI tag)
        (1, "EW1"),
        (3, "CA3"),
        (6, "CA2"),
        (9, "CA1"),
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

    # ── 4️⃣ EW1 / UG line (first two numbers only) ───────────────────────
    ew_ug_idx = None
    for i in range(zz0 + 1, len(lines)):
        if THREE_FLOAT_RE.match(lines[i]):
            ew_ug_idx = i
            break
    if ew_ug_idx is None:
        raise ValueError("Could not locate the ‘EW1 UG 0 …’ line")

    tokens = lines[ew_ug_idx].split()
    tokens[0] = fmt(v["EW1"])
    tokens[1] = fmt(v["UG"])
    lines[ew_ug_idx] = " ".join(tokens)

    # ── 6️⃣ inject real CROSSARM rows, no duplicates ─────────────────────
    _inject_crossarm_block(lines, v)

    # ── 7️⃣ write result ────────────────────────────────────────────────
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

    NOTE: This function no longer touches the .cpp or .xrm libraries – the
    user must press the “Modify libraries” button first.
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
tk.Button(root, text="Generate .POL", command=generate_pol)\
  .grid(row=len(FIELDS), columnspan=2, pady=8)

tk.Button(root, text="Modify libraries",
          command=lambda: (vals := collect_values()) and vals
                          and update_libraries(vals)
).grid(row=len(FIELDS)+1, columnspan=2, pady=4)



root.mainloop()
