"""Build the Tune-Up-only pricing workbook: three tiers, priced per door, $2,500 minimum.

Scope is the Tune-Up / Reconditioning service only (restore the existing finish; boxes,
doors and drawer fronts all stay). Refacing, redooring, painting and custom cabinets are
priced in the separate KTU_Tune-Up_Pricing_Calculator.xlsx workbook.

Rates marked "internal" come from the KTU internal rate card
(Drive: 02 Sales & Pricing / KTU_Custom_Kitchen_Price_Adjustments, 2026-06-05).
Per-door, per-drawer-front and job-base rates are assumption defaults set 2026-08-18.
"""

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

FONT = "Arial"
BLUE = Font(name=FONT, size=10, color="0000FF")
BLACK = Font(name=FONT, size=10)
GREEN = Font(name=FONT, size=10, color="008000")
BOLD = Font(name=FONT, size=10, bold=True)
RED = Font(name=FONT, size=10, bold=True, color="C00000")
H1 = Font(name=FONT, size=14, bold=True, color="FFFFFF")
H2 = Font(name=FONT, size=11, bold=True)
NOTE = Font(name=FONT, size=9, italic=True, color="595959")

HDR_FILL = PatternFill("solid", fgColor="1F3864")
INPUT_FILL = PatternFill("solid", fgColor="FFFF00")
BAND_FILL = PatternFill("solid", fgColor="D9E2F3")
TOTAL_FILL = PatternFill("solid", fgColor="E2EFDA")
MIN_FILL = PatternFill("solid", fgColor="FCE4D6")

MONEY = '$#,##0;($#,##0);-'
PCT = '0.0%'
thin = Side(style="thin", color="BFBFBF")
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)

# Tier, per door, per drawer front, job base, hrs/door, hrs/drawer front, base hrs
TIERS = [
    ("Tier 1 — Essential", 45, 25, 450, 0.30, 0.12, 4),
    ("Tier 2 — Enhanced", 60, 32, 550, 0.38, 0.16, 5),
    ("Tier 3 — Elite", 75, 40, 650, 0.48, 0.20, 6),
]

TIER_SCOPE = [
    ("Tier 1 — Essential",
     "Deep clean and degrease, restore the existing finish, colour-match minor scratches and "
     "water marks, tighten and adjust every door and drawer, re-set doors to square."),
    ("Tier 2 — Enhanced",
     "Everything in Tier 1, plus new knobs and pulls installed, hinge and drawer-glide "
     "adjustment or replacement, and repair of gouges, chips and worn edges."),
    ("Tier 3 — Elite",
     "Everything in Tier 2, plus full colour-matched repair of damaged doors and face frames, "
     "toe-kick and end-panel refresh, and an accessory or organiser allowance."),
]

ADDONS = [
    ("Hardware — material", "per piece", 17, "internal"),
    ("Hardware — install", "per piece", 17, "internal"),
    ("Rollout trays", "each", 275, "internal"),
    ("Trash pullout", "each", 450, "internal"),
    ("Lazy Susan", "each", 460, "internal"),
    ("Undercabinet lighting", "per job", 1150, "internal"),
    ("Add crown molding", "per run", 230, "internal"),
    ("Crown transition", "per piece", 230, "internal"),
    ("Matching end panels", "each", 192, "internal"),
    ("Refrigerator panel", "each", 345, "internal"),
    ("Repair drywall and spackle", "per area", 650, "internal"),
    ("Paint kitchen trims", "per job", 650, "internal"),
    ("Sink hook-up", "each", 385, "internal"),
    ("Granite / countertop tune-up", "per job", 450, "assumption"),
    ("Extra day on site", "per day", 900, "assumption"),
]

wb = Workbook()


def title(ws, text, width):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    c = ws.cell(row=1, column=1, value=text)
    c.font = H1
    c.fill = HDR_FILL
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24


def header_row(ws, row, values, start=1, size=10):
    for i, v in enumerate(values):
        c = ws.cell(row=row, column=start + i, value=v)
        c.font = Font(name=FONT, size=size, bold=True, color="FFFFFF")
        c.fill = HDR_FILL
        c.alignment = Alignment(horizontal="center", wrap_text=True, vertical="center")
        c.border = BOX


# ------------------------------------------------------------------ Rate Card
rc = wb.active
rc.title = "Rate Card"
title(rc, "TUNE-UP RATE CARD — owner-set. Edit the yellow cells; every tab follows them.", 8)
rc["A3"] = ("Per-door and per-drawer-front prices are LINE-ITEM prices. Shop Labor and Shop Overhead "
            "are added on top as their own proposal lines, exactly as in ServiceMinder.")
rc["A3"].font = NOTE

header_row(rc, 5, ["Tier", "Per Door", "Per Drawer Front", "Job Base",
                   "Hrs / Door", "Hrs / Drawer Front", "Base Hrs", "Crew Rate $/hr"])
for i, t in enumerate(TIERS):
    r = 6 + i
    rc.cell(row=r, column=1, value=t[0]).font = BOLD
    rc.cell(row=r, column=1).border = BOX
    for j, v in enumerate(t[1:]):
        c = rc.cell(row=r, column=2 + j, value=v)
        c.font = BLUE
        c.fill = INPUT_FILL
        c.border = BOX
        c.number_format = MONEY if j <= 2 else ('0.00' if j <= 4 else '0')
    c = rc.cell(row=r, column=8, value=65)
    c.font = BLUE
    c.fill = INPUT_FILL
    c.border = BOX
    c.number_format = MONEY
TIER_FIRST, TIER_LAST = 6, 5 + len(TIERS)

rc["A10"] = ("Source: per-door, per-drawer-front, job-base and crew-hour figures are ASSUMPTION defaults "
             "set 2026-08-18 — no per-door Tune-Up price list existed in the Drive or the repo. "
             "Confirm against recent signed Tune-Up proposals before field use. Crew rate $65/hr is the internal Track A rate.")
rc["A10"].font = NOTE

rc["A12"] = "SETTINGS"
rc["A12"].font = H2
settings = [
    ("Shop Labor %", 0.24, PCT, "Internal — its own proposal line"),
    ("Shop Overhead %", 0.05, PCT, "Internal — its own proposal line"),
    ("Job minimum ($)", 2500, MONEY, "Owner-set 2026-08-18 — no Tune-Up quotes below this"),
    ("Deposit %", 0.50, PCT, "Collected at signing"),
    ("Direct labor ceiling %", 0.20, PCT, "Internal target — flag any job above this"),
    ("Drawer fronts per door (matrix est.)", 0.45, '0.00', "Used only by the Price by Door Count tab"),
]
for i, (label, val, fmt, note) in enumerate(settings):
    r = 13 + i
    rc.cell(row=r, column=1, value=label).font = BOLD
    c = rc.cell(row=r, column=2, value=val)
    c.font = BLUE
    c.fill = INPUT_FILL
    c.number_format = fmt
    c.border = BOX
    rc.cell(row=r, column=3, value=note).font = NOTE

SHOP_LABOR = "'Rate Card'!$B$13"
OVERHEAD = "'Rate Card'!$B$14"
JOB_MIN = "'Rate Card'!$B$15"
DEPOSIT = "'Rate Card'!$B$16"
LABOR_CEIL = "'Rate Card'!$B$17"
DF_RATIO = "'Rate Card'!$B$18"

rc["A20"] = "WHAT EACH TIER INCLUDES"
rc["A20"].font = H2
header_row(rc, 21, ["Tier", "Scope"])
for i, (tier, scope) in enumerate(TIER_SCOPE):
    r = 22 + i
    rc.cell(row=r, column=1, value=tier).font = BOLD
    c = rc.cell(row=r, column=2, value=scope)
    c.font = BLACK
    c.alignment = Alignment(wrap_text=True, vertical="top")
    rc.row_dimensions[r].height = 42
    rc.cell(row=r, column=1).border = BOX
    c.border = BOX
rc.merge_cells("B22:H22")
rc.merge_cells("B23:H23")
rc.merge_cells("B24:H24")

rc["A26"] = "TUNE-UP ADD-ONS"
rc["A26"].font = H2
header_row(rc, 27, ["Add-On", "Unit", "Rate", "Source"])
for i, (name, unit, rate, src) in enumerate(ADDONS):
    r = 28 + i
    rc.cell(row=r, column=1, value=name).font = BLACK
    rc.cell(row=r, column=2, value=unit).font = BLACK
    c = rc.cell(row=r, column=3, value=rate)
    c.font = BLUE
    c.fill = INPUT_FILL
    c.number_format = MONEY
    rc.cell(row=r, column=4, value=(
        "KTU internal rate card, 2026-06-05" if src == "internal" else "Assumption — confirm")).font = NOTE
    for col in range(1, 5):
        rc.cell(row=r, column=col).border = BOX
ADDON_FIRST, ADDON_LAST = 28, 27 + len(ADDONS)

rc.column_dimensions["A"].width = 34
rc.column_dimensions["B"].width = 16
rc.column_dimensions["C"].width = 18
for col in "DEFGH":
    rc.column_dimensions[col].width = 14

# ------------------------------------------------------------------ Price by Door Count
pm = wb.create_sheet("Price by Door Count")
title(pm, "TUNE-UP PRICE BY DOOR COUNT — all-in, including Shop Labor, Overhead and the $2,500 minimum", 8)
pm["A3"] = ("Drawer fronts estimated at the Rate Card ratio (default 0.45 per door). Add-ons are not included. "
            "Shaded prices are jobs where the $2,500 minimum did the pricing, not the door count.")
pm["A3"].font = NOTE

header_row(pm, 5, ["Doors", "Drawer fronts (est.)",
                   "Tier 1 — Essential", "Tier 2 — Enhanced", "Tier 3 — Elite",
                   "Tier 1 per door", "Tier 2 per door", "Tier 3 per door"])
pm.row_dimensions[5].height = 32

doors = list(range(8, 62, 2))
for i, d in enumerate(doors):
    r = 6 + i
    c = pm.cell(row=r, column=1, value=d)
    c.font = BLUE
    c.number_format = '0'
    c.border = BOX
    c2 = pm.cell(row=r, column=2, value=f"=ROUND($A{r}*{DF_RATIO},0)")
    c2.font = BLACK
    c2.number_format = '0'
    c2.border = BOX
    for j in range(3):
        src = TIER_FIRST + j
        f = (f"=MAX({JOB_MIN},("
             f"'Rate Card'!$D${src}+$A{r}*'Rate Card'!$B${src}+$B{r}*'Rate Card'!$C${src}"
             f")*(1+{SHOP_LABOR}+{OVERHEAD}))")
        cc = pm.cell(row=r, column=3 + j, value=f)
        cc.font = BLACK
        cc.number_format = MONEY
        cc.border = BOX
        col = get_column_letter(3 + j)
        eff = pm.cell(row=r, column=6 + j, value=f"={col}{r}/$A{r}")
        eff.font = BLACK
        eff.number_format = MONEY
        eff.border = BOX

# Shade the rows where the minimum binds (computed here so the shading is static and readable).
for i, d in enumerate(doors):
    r = 6 + i
    df = round(d * 0.45)
    for j, t in enumerate(TIERS):
        raw = (t[3] + d * t[1] + df * t[2]) * 1.29
        if raw < 2500:
            pm.cell(row=r, column=3 + j).fill = MIN_FILL
            pm.cell(row=r, column=6 + j).fill = MIN_FILL

pm.cell(row=6 + len(doors) + 1, column=1,
        value="Shaded = the $2,500 minimum set the price. Below those door counts, quote $2,500 and trade the customer up with hardware, rollouts or lighting.").font = NOTE

pm.column_dimensions["A"].width = 8
pm.column_dimensions["B"].width = 16
for col in "CDEFGH":
    pm.column_dimensions[col].width = 17
pm.freeze_panes = "C6"

# ------------------------------------------------------------------ Quick Quote
qq = wb.create_sheet("Quick Quote")
title(qq, "TUNE-UP QUICK QUOTE — fill in the yellow cells only", 6)
qq["A3"] = "Blue text = you type it. Black = calculated. Green = pulled from the Rate Card."
qq["A3"].font = NOTE

qq["A5"] = "JOB INFO"
qq["A5"].font = H2
for i, (label, val) in enumerate([("Customer", "Example: Smith, 14 Maple Ave"),
                                  ("Date", "2026-08-18"),
                                  ("Sales rep", "Example: Ben")]):
    r = 6 + i
    qq.cell(row=r, column=1, value=label).font = BOLD
    c = qq.cell(row=r, column=2, value=val)
    c.font = BLUE
    c.fill = INPUT_FILL
    c.border = BOX

qq["A10"] = "SCOPE"
qq["A10"].font = H2
for i, (label, val) in enumerate([("Tier", "Tier 2 — Enhanced"),
                                  ("Door count", 28),
                                  ("Drawer front count", 12)]):
    r = 11 + i
    qq.cell(row=r, column=1, value=label).font = BOLD
    c = qq.cell(row=r, column=2, value=val)
    c.font = BLUE
    c.fill = INPUT_FILL
    c.border = BOX
    if isinstance(val, int):
        c.number_format = '0'
qq["C11"] = "← pick from the dropdown"
qq["C11"].font = NOTE
qq["C12"] = "Every hinged door, including pantry and appliance-panel doors."
qq["C12"].font = NOTE
qq["C13"] = "Every drawer front and false front."
qq["C13"].font = NOTE

dv = DataValidation(type="list", formula1=f"='Rate Card'!$A${TIER_FIRST}:$A${TIER_LAST}", allow_blank=False)
qq.add_data_validation(dv)
dv.add(qq["B11"])

TROW = f"MATCH($B$11,'Rate Card'!$A${TIER_FIRST}:$A${TIER_LAST},0)"

qq["A15"] = "TUNE-UP WORK"
qq["A15"].font = H2
header_row(qq, 16, ["Line", "Qty", "Rate", "Amount"])
lines = [
    ("Job base (measure, set-up, masking, clean-up)", 1,
     f"=INDEX('Rate Card'!$D${TIER_FIRST}:$D${TIER_LAST},{TROW})"),
    ("Doors", "=$B$12", f"=INDEX('Rate Card'!$B${TIER_FIRST}:$B${TIER_LAST},{TROW})"),
    ("Drawer fronts", "=$B$13", f"=INDEX('Rate Card'!$C${TIER_FIRST}:$C${TIER_LAST},{TROW})"),
]
for i, (label, qty, rate) in enumerate(lines):
    r = 17 + i
    qq.cell(row=r, column=1, value=label).font = BLACK
    c = qq.cell(row=r, column=2, value=qty)
    c.font = BLACK if isinstance(qty, str) else BLUE
    c.number_format = '0'
    c3 = qq.cell(row=r, column=3, value=rate)
    c3.font = GREEN
    c3.number_format = MONEY
    c4 = qq.cell(row=r, column=4, value=f"=B{r}*C{r}")
    c4.font = BLACK
    c4.number_format = MONEY
    for col in range(1, 5):
        qq.cell(row=r, column=col).border = BOX
qq["A20"] = "Tune-Up subtotal"
qq["A20"].font = BOLD
qq["D20"] = "=SUM(D17:D19)"
qq["D20"].font = BOLD
qq["D20"].number_format = MONEY
qq["D20"].fill = BAND_FILL

qq["A22"] = "ADD-ONS — enter a quantity for anything the job includes"
qq["A22"].font = H2
header_row(qq, 23, ["Add-On", "Qty", "Unit", "Rate", "Amount"])
for i in range(len(ADDONS)):
    r = 24 + i
    src = ADDON_FIRST + i
    qq.cell(row=r, column=1, value=f"='Rate Card'!A{src}").font = GREEN
    c = qq.cell(row=r, column=2, value=0)
    c.font = BLUE
    c.fill = INPUT_FILL
    c.number_format = '0.##'
    qq.cell(row=r, column=3, value=f"='Rate Card'!B{src}").font = GREEN
    c4 = qq.cell(row=r, column=4, value=f"='Rate Card'!C{src}")
    c4.font = GREEN
    c4.number_format = MONEY
    c5 = qq.cell(row=r, column=5, value=f"=B{r}*D{r}")
    c5.font = BLACK
    c5.number_format = MONEY
    for col in range(1, 6):
        qq.cell(row=r, column=col).border = BOX
ADD_FIRST, ADD_LAST = 24, 23 + len(ADDONS)
r = ADD_LAST + 1
qq.cell(row=r, column=1, value="Add-ons subtotal").font = BOLD
c = qq.cell(row=r, column=5, value=f"=SUM(E{ADD_FIRST}:E{ADD_LAST})")
c.font = BOLD
c.number_format = MONEY
c.fill = BAND_FILL
ADD_TOTAL = f"$E${r}"

p = r + 2
qq.cell(row=p, column=1, value="PRICE BUILD-UP").font = H2
build = [
    ("Line-item subtotal", f"=$D$20+{ADD_TOTAL}", BLACK),
    ("Shop Labor", f"=D{p+1}*{SHOP_LABOR}", BLACK),
    ("Shop Overhead", f"=D{p+1}*{OVERHEAD}", BLACK),
    ("Price before minimum", f"=SUM(D{p+1}:D{p+3})", BOLD),
    ("Job minimum", f"={JOB_MIN}", GREEN),
    ("Discount (enter as a positive $)", 0, BLUE),
    ("QUOTED PRICE", f"=MAX(D{p+4}-D{p+6},D{p+5})", Font(name=FONT, size=12, bold=True)),
    ("Effective price per door", f"=IFERROR(D{p+7}/$B$12,0)", BLACK),
    ("Deposit due at signing", f"=D{p+7}*{DEPOSIT}", BLACK),
    ("Balance", f"=D{p+7}-D{p+8}-D{p+9}+D{p+8}", BLACK),
]
for i, (label, val, font) in enumerate(build):
    rr = p + 1 + i
    qq.cell(row=rr, column=1, value=label).font = BOLD if font is BOLD else BLACK
    c = qq.cell(row=rr, column=4, value=val)
    c.font = font
    c.number_format = MONEY
    c.border = BOX
    if label.startswith("Discount"):
        c.fill = INPUT_FILL
    if label == "QUOTED PRICE":
        c.fill = TOTAL_FILL
# Balance = quoted - deposit (written plainly)
qq.cell(row=p + 10, column=4, value=f"=D{p+7}-D{p+9}")
QUOTED = f"$D${p+7}"
qq.cell(row=p + 7, column=5,
        value=f'=IF({QUOTED}<=D{p+5},"MINIMUM APPLIED — this job priced up to the $2,500 floor. Trade up: hardware, rollouts, lighting.","")').font = RED

m = p + 12
qq.cell(row=m, column=1, value="MARGIN CHECK (internal — do not show the customer)").font = H2
qq.cell(row=m, column=1).fill = MIN_FILL
mrows = [
    ("Estimated crew hours",
     f"=INDEX('Rate Card'!$G${TIER_FIRST}:$G${TIER_LAST},{TROW})"
     f"+$B$12*INDEX('Rate Card'!$E${TIER_FIRST}:$E${TIER_LAST},{TROW})"
     f"+$B$13*INDEX('Rate Card'!$F${TIER_FIRST}:$F${TIER_LAST},{TROW})", '0.0'),
    ("Crew rate ($/hr)", f"=INDEX('Rate Card'!$H${TIER_FIRST}:$H${TIER_LAST},{TROW})", MONEY),
    ("Estimated direct labor cost", f"=D{m+1}*D{m+2}", MONEY),
    ("Direct labor % of quoted price", f"=IFERROR(D{m+3}/{QUOTED},0)", PCT),
]
for i, (label, val, fmt) in enumerate(mrows):
    rr = m + 1 + i
    qq.cell(row=rr, column=1, value=label).font = BLACK
    c = qq.cell(row=rr, column=4, value=val)
    c.font = BLACK
    c.number_format = fmt
    c.border = BOX
qq.cell(row=m + 4, column=5,
        value=f'=IF(D{m+4}>{LABOR_CEIL},"OVER the 20% labor ceiling — re-check hours or raise the price","Within the 20% labor ceiling")').font = BOLD
qq.cell(row=m + 6, column=1,
        value="Hours are estimated from scope, not Construction Clock actuals. Materials and finish product are not in this check.").font = NOTE

qq.column_dimensions["A"].width = 44
qq.column_dimensions["B"].width = 10
qq.column_dimensions["C"].width = 16
qq.column_dimensions["D"].width = 16
qq.column_dimensions["E"].width = 60

# ------------------------------------------------------------------ How It Works
hp = wb.create_sheet("How Tune-Up Pricing Works", 0)
title(hp, "HOW TUNE-UP PRICING WORKS", 1)
content = [
    ("H", "What a Tune-Up is"),
    ("T", "The 1-day reconditioning service: we restore the finish that is already on the cabinets. Boxes, doors and drawer fronts all stay. No colour change, no style change, and it cannot be done on painted or laminate doors — those are painting or redooring jobs, priced on the other workbook."),
    ("B", ""),
    ("H", "The formula"),
    ("T", "Quoted price = ( Job base + Doors x Per-door rate + Drawer fronts x Per-drawer-front rate + Add-ons ) x 1.29, floored at $2,500."),
    ("T", "The 1.29 is Shop Labor 24% + Shop Overhead 5%, which go on the proposal as their own two lines, same as always in ServiceMinder."),
    ("B", ""),
    ("H", "Why per door"),
    ("T", "The boxes stay put, so the work scales with the number of doors and drawer fronts, not with the size of the kitchen. Count the doors, count the drawer fronts, and the job prices itself. The job base covers measure, set-up, masking and clean-up — it is why a 12-door kitchen is not half the price of a 24-door kitchen."),
    ("B", ""),
    ("H", "The three tiers"),
    ("T", "Tier 1 Essential — $45/door, $25/drawer front, $450 base. Deep clean and degrease, restore the existing finish, colour-match minor scratches and water marks, tighten and adjust every door and drawer."),
    ("T", "Tier 2 Enhanced — $60/door, $32/drawer front, $550 base. Everything in Tier 1, plus new knobs and pulls installed, hinge and drawer-glide adjustment or replacement, and repair of gouges, chips and worn edges."),
    ("T", "Tier 3 Elite — $75/door, $40/drawer front, $650 base. Everything in Tier 2, plus full colour-matched repair of damaged doors and face frames, toe-kick and end-panel refresh, and an accessory or organiser allowance."),
    ("B", ""),
    ("H", "The $2,500 minimum"),
    ("T", "No Tune-Up goes out below $2,500. Under that number the drive time, measure, product minimums and set-up eat the entire margin. On this service the floor binds often: roughly under 27 doors at Tier 1, under 19 at Tier 2, under 14 at Tier 3. Those jobs are quoted at $2,500 and the sheet flags them."),
    ("T", "Treat the flag as a trade-up moment, not an apology. The customer is paying $2,500 either way, so move them up a tier or add hardware, rollouts, a trash pullout or under-cabinet lighting and they get real value for the same check."),
    ("B", ""),
    ("H", "Add-ons"),
    ("T", "Hardware, rollouts, pullouts, lighting, crown, panels, drywall and trim paint price separately off the Rate Card and ride through the same shop labor and overhead math. Enter a quantity on the Quick Quote tab."),
    ("B", ""),
    ("H", "The margin guardrail"),
    ("T", "Every quote estimates crew hours from the scope and flags any job where direct labor runs over 20% of price — the internal ceiling. A flag means re-check the hour estimate or raise the price before it is signed."),
    ("B", ""),
    ("H", "Who changes what"),
    ("T", "Reps fill in the yellow cells on Quick Quote only. All rates live on the Rate Card tab and are owner-set, so every rep quotes the same kitchen the same way."),
    ("B", ""),
    ("H", "Where the numbers came from"),
    ("T", "Add-on rates, Shop Labor 24%, Shop Overhead 5% and the 20% labor ceiling are existing internal figures (KTU internal rate card, 2026-06-05, and the internal service-line standards). The $2,500 minimum is owner-set, 2026-08-18."),
    ("T", "The per-door, per-drawer-front and job-base rates are assumption defaults set 2026-08-18 — no per-door Tune-Up price list existed in the Drive or the repo. Confirm them against recent signed Tune-Up proposals, then change them once on the Rate Card tab."),
]
r = 3
for kind, text in content:
    if kind == "B":
        r += 1
        continue
    c = hp.cell(row=r, column=1, value=text)
    c.font = H2 if kind == "H" else Font(name=FONT, size=10)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    if kind == "T":
        hp.row_dimensions[r].height = 32
    r += 1
hp.column_dimensions["A"].width = 132

wb.save("/home/user/TeamLivingston/docs/pricing/KTU_TuneUp_Pricing.xlsx")
print("written")
