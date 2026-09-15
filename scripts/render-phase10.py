"""Render the Phase 10 memo, committee brief, and decision charts.

Run with the bundled Python runtime that provides ReportLab, Pillow, and pypdf.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


NAVY = colors.HexColor("#17365D")
BLUE = colors.HexColor("#1F4E78")
MID_BLUE = colors.HexColor("#4472C4")
PALE_BLUE = colors.HexColor("#D9EAF7")
PALE_TAN = colors.HexColor("#FAF4EA")
PALE_RED = colors.HexColor("#FCE4D6")
GRAY = colors.HexColor("#F2F2F2")
LINE = colors.HexColor("#B7C9D6")
TEXT = colors.HexColor("#222222")
WHITE = colors.white
STATUS = "owner_reviewed | Conditional Approval — proceed with diligence and definitive documentation."
NO_FINAL_AUTHORIZATION = "No final commitment or funding authorization exists until all material conditions are satisfied."


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def metric_map(root: Path) -> dict[tuple[str, str], dict[str, str]]:
    rows = read_csv(root / "data" / "phase10" / "processed" / "COMMITTEE_METRICS.csv")
    return {(row["metric_name"], row["scenario_or_period"]): row for row in rows}


def value(metrics: dict[tuple[str, str], dict[str, str]], name: str, period: str) -> str:
    return metrics[(name, period)]["display_value"]


def ref(metrics: dict[tuple[str, str], dict[str, str]], name: str, period: str) -> str:
    row = metrics[(name, period)]
    return f"{row['display_value']} [{row['metric_id']}]"


def font(size: int = 14, bold: bool = False):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_bar_chart(path: Path, title: str, labels: list[str], values: list[float],
                   colors_rgb: list[tuple[int, int, int]], unit: str) -> None:
    width, height = 1200, 540
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((55, 28), title, fill=(23, 54, 93), font=font(30, True))
    left, top, right, bottom = 85, 105, 1140, 440
    draw.line((left, bottom, right, bottom), fill=(150, 165, 178), width=2)
    max_value = max(values) * 1.12 if values else 1
    slot = (right - left) / len(values)
    bar_width = slot * 0.58
    for index, (label, number, color) in enumerate(zip(labels, values, colors_rgb)):
        x0 = left + slot * index + (slot - bar_width) / 2
        x1 = x0 + bar_width
        y0 = bottom - (number / max_value) * (bottom - top)
        draw.rounded_rectangle((x0, y0, x1, bottom), radius=7, fill=color)
        shown = f"{number:.1f}{unit}"
        box = draw.textbbox((0, 0), shown, font=font(18, True))
        draw.text(((x0 + x1 - (box[2] - box[0])) / 2, y0 - 26), shown, fill=(34, 34, 34), font=font(18, True))
        parts = label.split("\n")
        for j, part in enumerate(parts):
            box = draw.textbbox((0, 0), part, font=font(15))
            draw.text(((x0 + x1 - (box[2] - box[0])) / 2, bottom + 12 + j * 19), part, fill=(34, 34, 34), font=font(15))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False)


def build_charts(root: Path, metrics: dict[tuple[str, str], dict[str, str]]) -> list[Path]:
    out = root / "reports" / "charts"
    cash = out / "historical_cash_conversion.png"
    maturity = out / "maturity_gap_comparison.png"
    recovery = out / "recovery_sensitivities.png"
    make_bar_chart(
        cash,
        "Historical cash conversion (% of lender-base EBITDA)",
        ["FY2024\nCFO", "FY2024\nFCF", "FY2025\nCFO", "FY2025\nFCF"],
        [float(metrics[("cfo_to_provisional_lender_normalized_ebitda", "FY2024")]["value"]),
         float(metrics[("fcf_to_provisional_lender_normalized_ebitda", "FY2024")]["value"]),
         float(metrics[("cfo_to_provisional_lender_normalized_ebitda", "FY2025")]["value"]),
         float(metrics[("fcf_to_provisional_lender_normalized_ebitda", "FY2025")]["value"])],
        [(68, 114, 196), (140, 176, 224), (31, 78, 121), (91, 155, 213)], "%",
    )
    make_bar_chart(
        maturity,
        "Unsupported maturity gap by selected path (USD millions)",
        ["Base", "Moderate\nunmitigated", "Moderate\nmitigated", "Severe\nunmitigated", "Severe\nmitigated"],
        [float(metrics[("unsupported_maturity_gap", key)]["value"]) for key in
         ("BASE", "MODERATE_UNMITIGATED", "MODERATE_MITIGATED", "SEVERE_UNMITIGATED", "SEVERE_MITIGATED")],
        [(31, 78, 121), (237, 166, 62), (99, 168, 116), (190, 73, 64), (136, 99, 168)], "",
    )
    recovery_values = [
        float(metrics[("going_concern_recovery", key)]["value"]) for key in ("Low", "Base", "High")
    ] + [float(metrics[("asset_realization_recovery", key)]["value"]) for key in ("Low", "Base", "High")]
    make_bar_chart(
        recovery,
        "Illustrative alternative recovery sensitivities (% of facility claim)",
        ["GC\nLow", "GC\nBase", "GC\nHigh", "Asset ceiling\nLow", "Asset ceiling\nBase", "Asset ceiling\nHigh"],
        recovery_values,
        [(68, 114, 196)] * 3 + [(160, 160, 160)] * 3,
        "%",
    )
    return [cash, maturity, recovery]


class PageWriter:
    def __init__(self, c: canvas.Canvas, title: str, page_no: int, total: int,
                 page_size=LETTER, appendix: bool = False):
        self.c = c
        self.width, self.height = page_size
        self.left = 42
        self.right = self.width - 42
        self.y = self.height - 72
        self.page_no = page_no
        self.total = total
        self.document_title = title
        self.appendix = appendix
        self.header()

    def header(self) -> None:
        self.c.setFillColor(NAVY)
        self.c.rect(0, self.height - 44, self.width, 44, fill=1, stroke=0)
        self.c.setFillColor(WHITE)
        self.c.setFont("Helvetica-Bold", 11)
        self.c.drawString(42, self.height - 27, self.document_title)
        self.c.setFont("Helvetica", 7.5)
        self.c.drawRightString(self.width - 42, self.height - 27, "Cutoff December 15, 2025 | Hypothetical close January 31, 2026")
        self.c.setFillColor(TEXT)
        # Keep the complete classification line clear of the independently
        # positioned page number on both memo-body and appendix pages.
        self.c.setFont("Helvetica", 6.2)
        label = "TECHNICAL APPENDIX" if self.appendix else "MEMO BODY"
        self.c.drawString(42, 25, f"{label} | Public-information hypothetical transaction | {STATUS}")
        self.c.setFont("Helvetica", 7.5)
        self.c.drawRightString(self.width - 42, 25, f"Page {self.page_no} of {self.total}")
        self.c.setStrokeColor(LINE)
        self.c.line(42, 35, self.width - 42, 35)

    def section(self, title: str, height: float = 22) -> None:
        self.y -= 3
        self.c.setFillColor(BLUE)
        self.c.roundRect(self.left, self.y - height + 3, self.right - self.left, height, 3, fill=1, stroke=0)
        self.c.setFillColor(WHITE)
        self.c.setFont("Helvetica-Bold", 11)
        self.c.drawString(self.left + 8, self.y - 11, title)
        self.y -= height + 5

    def heading(self, text: str, size: float = 10.5) -> None:
        self.c.setFillColor(NAVY)
        self.c.setFont("Helvetica-Bold", size)
        self.c.drawString(self.left, self.y, text)
        self.y -= size + 6

    @staticmethod
    def wrap(text: str, width: float, font_name: str, font_size: float) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else current + " " + word
            if stringWidth(candidate, font_name, font_size) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def paragraph(self, text: str, width: float | None = None, size: float = 8.7,
                  leading: float = 11.2, color=TEXT, bold_prefix: str | None = None,
                  indent: float = 0) -> None:
        width = width or (self.right - self.left - indent)
        font_name = "Helvetica"
        self.c.setFillColor(color)
        self.c.setFont(font_name, size)
        for line in self.wrap(text, width, font_name, size):
            self.c.drawString(self.left + indent, self.y, line)
            self.y -= leading
        self.y -= 4

    def bullet(self, text: str, size: float = 8.4, leading: float = 10.5) -> None:
        width = self.right - self.left - 16
        lines = self.wrap(text, width, "Helvetica", size)
        self.c.setFillColor(TEXT)
        self.c.setFont("Helvetica", size)
        self.c.drawString(self.left + 2, self.y, "-")
        for i, line in enumerate(lines):
            self.c.drawString(self.left + 14, self.y, line)
            if i < len(lines) - 1:
                self.y -= leading
        self.y -= leading + 1

    def callout(self, title: str, text: str, fill=PALE_BLUE, height: float = 64) -> None:
        self.c.setFillColor(fill)
        self.c.setStrokeColor(LINE)
        self.c.roundRect(self.left, self.y - height, self.right - self.left, height, 4, fill=1, stroke=1)
        self.c.setFillColor(NAVY)
        self.c.setFont("Helvetica-Bold", 9.2)
        self.c.drawString(self.left + 9, self.y - 16, title)
        yy = self.y - 30
        self.c.setFillColor(TEXT)
        self.c.setFont("Helvetica", 8)
        for line in self.wrap(text, self.right - self.left - 18, "Helvetica", 8):
            self.c.drawString(self.left + 9, yy, line)
            yy -= 10
        self.y -= height + 8

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float],
              row_height: float = 22, font_size: float = 7.5, header_height: float | None = None,
              alternating: bool = True) -> None:
        header_height = header_height or row_height
        x = self.left
        self.c.setFillColor(NAVY)
        self.c.rect(x, self.y - header_height, sum(widths), header_height, fill=1, stroke=0)
        for header, width in zip(headers, widths):
            self.c.setFillColor(WHITE)
            self.c.setFont("Helvetica-Bold", font_size)
            lines = self.wrap(header, width - 6, "Helvetica-Bold", font_size)[:2]
            yy = self.y - 9
            for line in lines:
                self.c.drawString(x + 3, yy, line)
                yy -= font_size + 1
            x += width
        self.y -= header_height
        for index, row in enumerate(rows):
            x = self.left
            if alternating and index % 2:
                self.c.setFillColor(GRAY)
                self.c.rect(x, self.y - row_height, sum(widths), row_height, fill=1, stroke=0)
            self.c.setStrokeColor(LINE)
            self.c.line(x, self.y - row_height, x + sum(widths), self.y - row_height)
            for cell, width in zip(row, widths):
                self.c.setFillColor(TEXT)
                self.c.setFont("Helvetica", font_size)
                lines = self.wrap(str(cell), width - 6, "Helvetica", font_size)[:3]
                yy = self.y - 9
                for line in lines:
                    self.c.drawString(x + 3, yy, line)
                    yy -= font_size + 1
                x += width
            self.y -= row_height
        self.y -= 7

    def image(self, path: Path, width: float, height: float) -> None:
        self.c.drawImage(ImageReader(path), self.left, self.y - height, width=width, height=height, preserveAspectRatio=True, mask="auto")
        self.y -= height + 7


def build_memo(root: Path, metrics: dict[tuple[str, str], dict[str, str]], charts: list[Path]) -> Path:
    path = root / "reports" / "credit_memo.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER, pageCompression=1, invariant=1)
    c.setTitle("Quanex Credit Committee Memorandum")
    total = 11

    p = PageWriter(c, "Quanex credit committee memorandum", 1, total)
    p.section("1. Decision and exposure")
    p.callout("CONDITIONAL APPROVAL - PROCEED WITH DILIGENCE AND DEFINITIVE DOCUMENTATION",
              "$635m fully funded term facility plus $300m revolver; participating-bank hold up to $50m combined. "
              f"Status: owner_reviewed. {NO_FINAL_AUTHORIZATION}", PALE_BLUE, 78)
    p.table(["Question", "Committee answer"], [
        ["What are we lending?", "$635m term + $300m revolver; $29.898m opening draw; $15m non-debt source required."],
        ["Why refinance?", "$5.000m lower same-date closing debt only from the conditional source. Benefits are maturity, liquidity, amortization, sweep, reporting, and intervention."],
        ["How are we repaid?", "Primary: recurring operating cash after all required uses. Amortization/sweep are payment mechanisms. Recovery is the secondary backstop."],
        ["What can go wrong?", "3.2285x opening leverage; moderate breach 10/31/26; severe liquidity/payment failure; Tyman/control risk; $324.780m 01/31/31 gap."],
        ["Why acceptable?", "Moderate breach enables early intervention while liquidity/payment capacity remain; no automatic waiver; failed conditions trigger fallback."],
    ], [118, 410], row_height=43, font_size=7.6)
    p.table(["Decision field", "Result", "Source"], [
        ["Borrower", "Quanex Building Products Corporation", "Phase 0 mandate"],
        ["Opening debt / leverage", f"{value(metrics,'opening_funded_debt','selected')} / {value(metrics,'opening_gross_leverage','selected')}", "P10M-021/022"],
        ["Base all-in liquidity", value(metrics,'base_all_in_liquidity','selected'), "P10M-023"],
        ["Borrower risk assessment", "Elevated - project-specific qualitative", "Phase 10 register"],
        ["Official recovery", "N/D", "P10M-096"],
    ], [150, 245, 133], row_height=25, font_size=7.5)
    p.paragraph("Critical failure rule: if the $15m source, satisfactory closing coverage, acceptable documents, full commitments, or another material condition is absent, resize, obtain another acceptable non-debt source, or do not close. Do not add debt, loosen covenants, assume inaccessible cash, refinancing, waiver, or recovery. Retain or amend existing facilities through a limited amendment/extension.", size=8.4)
    c.showPage()

    p = PageWriter(c, "Quanex credit committee memorandum", 2, total)
    p.section("2. Transaction and alternatives")
    p.heading("Selected structure and sources / uses")
    p.table(["Item", "Selected treatment", "Boundary"], [
        ["Term facility", "$635.000m funded at close", "No unused term availability"],
        ["Revolver", "$300.000m commitment; $29.898m opening draw", "$6.2m LCs counted once"],
        ["Non-debt source", "$15.000m conditional", "Separate from $25m operating floor"],
        ["Sources less uses", "$0.000m", "Final payoff and funds flow required"],
        ["Amortization / sweep", "7.5% annual quarterly / 50% ECF", "Final definitions and safeguards required"],
        ["Final maturity", "January 31, 2031", "No refinancing proceeds assumed"],
    ], [120, 205, 203], row_height=25, font_size=7.3)
    p.heading("Why Quanex would refinance")
    for text in [
        "Persistent acquisition-related revolver usage is moved into amortizing term debt, leaving the revolver primarily for working capital.",
        "The selected package adds mandatory amortization, an ECF sweep, distribution restrictions, and warning/covenant reporting that provide earlier lender intervention.",
        "Final maturity extends roughly 18 months beyond the existing August 1, 2029 maturity; extension is modest and not sufficient by itself.",
    ]:
        p.bullet(text)
    p.heading("Live alternatives and strongest counterargument")
    p.table(["01/31/2026 projected alternative", "Bank debt", "Other funded debt", "Total funded debt"], [
        ["Existing facilities", "$669.898m", "$62.619m", "$732.517m"],
        ["$650m reference", "$679.898m", "$62.619m", "$742.517m"],
        ["$635m selected", "$664.898m", "$62.619m", "$727.517m"],
    ], [170, 115, 115, 128], row_height=21, font_size=7.1)
    p.paragraph("Historical reference only at 10/31/2025: $641.250m bank debt + $62.619m retained lease/other debt = $703.869m total funded debt. Selected is $5.000m below projected existing at 01/31/2026 only because the conditional $15m non-debt source exceeds assumed $10m fees.", size=7.8, color=NAVY)
    p.callout("STRONGEST COUNTERARGUMENT",
              "Refinancing incurs fees and unresolved economics; at 07/31/2029 selected debt is $514.754m, $19.385m above existing; moderate stress breaches 10/31/2026; refinancing remains unresolved; and the lower selected gap benefits partly from about 18 extra months.", PALE_TAN, 66)
    p.paragraph("Response: the refinance is not justified by faster same-horizon debt reduction. It is supportable only for maturity extension, liquidity structure, amortization, lender protections, and monitoring, subject to acceptable final economics and documents. Otherwise the fallback controls.", size=8.5)
    p.table(["Alternative", "07/31/29 total funded debt", "Ultimate bank-debt gap / date"], [
        ["Retain existing", "$495.368m", "$432.749m / 08/01/2029"],
        ["Limited amendment", "N/D", "Terms and economics N/D"],
        ["$650m reference", "$507.954m", "$340.948m / 01/31/2031"],
        ["$635m selected", "$514.754m", "$324.780m / 01/31/2031"],
    ], [125, 165, 238], row_height=20, font_size=7.2)
    p.paragraph("Selected is $19.385m above existing and $6.800m above reference at the common horizon. Ultimate bank-debt gaps use different maturity dates and cash-generation periods and are not directly comparable.", size=8.2, color=NAVY)
    c.showPage()

    p = PageWriter(c, "Quanex credit committee memorandum", 3, total)
    p.section("3. Borrower and business risk")
    p.paragraph("Quanex supplies building-product components through Hardware, Extruded, and Custom Solutions. Demand is exposed to residential repair/remodeling, new construction, and selected commercial/industrial markets. The underwriting is a post-Tyman integration case, not a pre-acquisition steady-state credit.", size=8.7)
    p.table(["Risk driver", "Evidence / mechanism", "Required lender response"], [
        ["Demand and volume", "Legacy revenue fell in FY2024; pre-cutoff housing indicators were weak; post-acquisition growth is not organic.", "Comparable-volume and price/mix bridge by segment/geography."],
        ["Gross margin", "Seasonal and acquisition/mix effects; fixed-cost absorption is the primary operating sensitivity.", "Monthly plant, service-level, mix, and margin reporting."],
        ["Tyman integration", "$302.284m goodwill impairment; plant stabilization and remaining synergy realization are uncertain.", "Milestone, cash-cost, service, and realized-synergy evidence."],
        ["Working capital", "FY2025 DIO 72.22 days; quarterly cash generation is seasonal; DPO is N/D.", "Aging, purchases/AP, accrual, and other-WC bridge; no zero plug."],
        ["Capital expenditure", "FY2025 capex $62.642m; maintenance versus integration/expansion split is unavailable.", "Project-level schedule; no unsupported maintenance cut."],
        ["Reporting quality", "Cash-flow statement preparation/review material weakness remained outstanding at FY2025 year-end.", "Remediation milestones, testing evidence, and audit updates."],
        ["Foreign cash / structure", "$46.9m of FY2025 book cash was foreign; accessibility is not equivalent to book cash.", "Entity/jurisdiction cash and guarantor/collateral schedule."],
    ], [116, 232, 180], row_height=51, font_size=7.1)
    p.callout("Acquisition comparability boundary",
              "FY2021-FY2023 are pre-Tyman; FY2024 includes roughly three months of Tyman; FY2025 is the first full post-Tyman year. Pro forma figures do not create reported history, and current segments are not fabricated backward.", PALE_BLUE, 65)
    p.paragraph("Underwriting judgment: business scale and FY2025 earnings capacity support proceeding, but integration, plant execution, margin, working capital, and reporting controls make the recommendation conditional and support an Elevated project-specific qualitative risk assessment - not an official bank grade or agency rating.", size=8.6)
    c.showPage()

    p = PageWriter(c, "Quanex credit committee memorandum", 4, total)
    p.section("4. Historical performance and earnings quality")
    p.table(["USD millions / ratio", "FY2024", "FY2025", "Credit interpretation"], [
        ["Revenue", "$1,277.862m", "$1,837.641m", "Growth is acquisition-distorted"],
        ["Operating income", "$54.826m", "$(193.952)m", "FY2025 includes impairment"],
        ["Unadjusted EBITDA", "$115.154m", "$(90.508)m", "Negative FY2025; ratio denominator N/M"],
        ["Lender-base EBITDA", "$179.358m", "$225.344m", "Owner-reviewed normalization; not contractual EBITDA"],
        ["CFO", "$88.812m", "$164.897m", "Includes cash interest under US GAAP"],
        ["FCF", "$51.726m", "$102.255m", "Defined as CFO less capex"],
        ["Cash interest paid", value(metrics, "cash_interest_paid_disclosed", "FY2024"), value(metrics, "cash_interest_paid_disclosed", "FY2025"), "Original annual-report disclosure"],
        ["Lender EBITDA / cash paid interest", value(metrics, "historical_lender_ebitda_to_disclosed_cash_interest_paid", "FY2024"), value(metrics, "historical_lender_ebitda_to_disclosed_cash_interest_paid", "FY2025"), "Historical diagnostic; not closing or contractual coverage"],
        ["CFO / lender EBITDA", "49.5%", "73.2%", "FY2025 recovery is supportive"],
        ["FCF / lender EBITDA", "28.8%", "45.4%", "Still subject to seasonality and capex mix"],
    ], [132, 82, 82, 232], row_height=25, font_size=6.9)
    p.image(charts[0], 520, 234)
    p.heading("Earnings-definition bridge")
    p.paragraph("FY2025 unadjusted EBITDA of $(90.508)m is bridged to $225.344m lender-base EBITDA primarily through the $302.284m impairment, $9.007m inventory purchase-accounting step-up, and $4.561m identified noncash restructuring component. Plant-relocation items and the $10.263m composite receive no Base credit. FY2024 lender Base accepts the $29.076m purchase-accounting normalization and $39.324m Tyman transaction fees, deducts the $(4.196)m gain, and rejects the plant-closure cost in Base.", size=8.1)
    p.callout("Cash-flow boundary",
              "Lender-normalization, contractual eligibility, historical cash-paid interest, and forecast paid-or-payable coverage remain separate. Cash interest is already in US-GAAP CFO and is not deducted twice.", PALE_TAN, 55)
    c.showPage()

    p = PageWriter(c, "Quanex credit committee memorandum", 5, total)
    p.section("5. Debt, legal structure, and liquidity")
    p.table(["Measure", "Selected result", "Interpretation"], [
        ["Term / revolver", "$635m / $300m", "Term fully funded; revolver for working capital"],
        ["Opening revolver draw", "$29.898m", "Not unused term availability"],
        ["Retained funded obligations", "$62.619m", "Included economically; legal ranking N/D"],
        ["Opening funded debt", "$727.517m", "Term + revolver + retained funded obligations"],
        ["Opening gross leverage", "3.2285x", "Below but close to 3.25x inclusive warning"],
        ["Opening / all-in liquidity", "$263.902m", "No credit to book cash"],
        ["Operating floor", "$25.000m", "Separate from covenant liquidity and source"],
        ["Bank hold", "Up to $50.000m", "Combined commitments; allocation remains final"],
    ], [145, 125, 258], row_height=31, font_size=7.4)
    p.heading("Legal and collateral conditions")
    for text in [
        "Executed guarantees from eligible material domestic subsidiaries; final entity and excluded-subsidiary schedules.",
        "Payoff and lien releases, collateral scope, UCC/IP filings, control agreements, searches, perfection, priority, and permitted-lien review.",
        "No assumption that foreign cash or all consolidated assets are accessible or pledged; entity-level treatment must be documented.",
        "LC replacement/continuation mechanics, final draw conditions, defaults, cures, waivers, ECF, debt, and EBITDA definitions.",
    ]:
        p.bullet(text, size=8.2)
    p.heading("Liquidity and drawability")
    p.paragraph("Usable liquidity equals eligible unrestricted cash plus undrawn drawable revolver capacity after LCs. Book cash is excluded unless final evidence proves eligibility. A warning is not a breach and does not itself stop draws. The no-waiver path is a separate covenant-linked sensitivity; legal availability is determined only by executed documents.", size=8.5)
    p.callout("Closing coverage remains N/D",
              "The public record lacks a complete closing-date LTM cash-interest denominator under final definitions. Satisfactory closing coverage evidence is a condition precedent, not a modeled assumption.", PALE_RED, 55)
    c.showPage()

    p = PageWriter(c, "Quanex credit committee memorandum", 6, total)
    p.section("6. Base repayment and refinancing")
    p.table(["Base measure", "Result", "Credit meaning"], [
        ["FY2026 post-closing EBITDA", "$190.249m", "Nine months, February 1-October 31, 2026; not annual"],
        ["Modeled operating cash", "$794.484m", "Cumulative 02/01/2026-01/31/2031"],
        ["CFADS", "$640.309m", "Cumulative 02/01/2026-01/31/2031"],
        ["Cash interest", "$167.386m", "Cumulative 02/01/2026-01/31/2031"],
        ["Scheduled principal", "$238.125m", "Cumulative 02/01/2026-01/31/2031"],
        ["ECF sweep", "$57.292m", "Cumulative 02/01/2026-01/31/2031"],
        ["Minimum coverage", "5.3860x", "Minimum over forecast"],
        ["Common-horizon funded debt", "$514.754m", "Total funded debt at 07/31/2029"],
        ["Unsupported maturity gap", "$324.780m", "Bank debt at 01/31/2031; no takeout"],
    ], [145, 115, 268], row_height=24, font_size=7.4)
    p.image(charts[1], 520, 232)
    p.heading("Repayment conclusion")
    p.paragraph("Primary repayment is recurring operating cash available after operating requirements, cash interest, cash taxes, working-capital needs, necessary maintenance capex, and other required uses. Scheduled amortization and the ECF sweep are payment mechanisms, not sources. Accessible cash and legally drawable revolver capacity are timing/liquidity support only; a draw increases or reallocates funded debt. Refinancing is an unresolved separately underwritten dependency, not secondary repayment. Collateral/business-sale recovery is the secondary backstop; official recovery is N/D.", size=8.4)
    p.callout("Residual maturity dependency",
              "The selected structure does not self-liquidate. A funded maturity strategy must begin at least 24 months before January 31, 2031 and escalate at 12 months without an executable solution. A maturity gap is refinancing risk, not a forecast default conclusion.", PALE_TAN, 61)
    c.showPage()

    p = PageWriter(c, "Quanex credit committee memorandum", 7, total)
    p.section("7. Downside and covenant intervention")
    p.table(["Selected path", "Maximum quarterly-test leverage / min coverage", "Liquidity and event", "Maturity gap"], [
        ["Base", "3.23x / 5.39x", "$263.902m all-in; no modeled breach/failure", "$324.780m"],
        ["Moderate unmitigated", "4.4893x / 3.2104x", "$165.078m; breach 10/31/2026; no failure", "$408.375m"],
        ["Moderate mitigated", "4.4670x / 3.2168x", "$168.937m; breach 10/31/2026; no failure", "$381.133m"],
        ["Severe unmitigated", "7.06x / 1.78x", "$0; liquidity 07/31/2027; cash-interest failure 12/31/2027", "$604.258m"],
        ["Severe mitigated", "6.95x / 1.80x", "$0; scheduled-principal failure 01/31/2028", "$554.718m"],
    ], [112, 118, 205, 93], row_height=40, font_size=7.0)
    p.heading("8. Recovery and risk assessment")
    p.paragraph("Moderate unmitigated/mitigated leverage peaks at 4.4893x/4.4670x; coverage bottoms at 3.2104x/3.2168x. Both warn and breach 10/31/2026. Liquidity remains $165.078m/$168.937m; neither modeled path exhausts liquidity or fails payment. Mitigation does not restore compliance; no automatic waiver is assumed. At the severe first-payment-failure date, illustrative recovery methods remain alternatives and official recovery is N/D. Recovery does not improve the Elevated project-specific assessment.", size=8.2)
    p.heading("9. Conditions, monitoring, and conclusion")
    p.paragraph("Conditions precedent address the $15m source, funds flow, closing coverage, final definitions/economics, guarantees, collateral, accessible cash, LCs, projections, legal/KYC/tax/authority, and full commitments. Ongoing protections address distributions, minimum liquidity, certificates, monthly operating/cash reporting, control remediation, and maturity planning. Analyst warnings remain distinct from legal breaches.", size=8.1)
    p.callout("CONDITIONAL APPROVAL - PROCEED WITH DILIGENCE AND DEFINITIVE DOCUMENTATION",
              f"Owner-review status: owner_reviewed. {NO_FINAL_AUTHORIZATION} Early moderate breach is accepted only as intervention while liquidity/payment capacity remain. If diligence indicates moderate is near expected, resize, require non-debt capital, restructure, or do not close. Failed conditions cannot be replaced with debt or covenant relief; retain or amend existing facilities through a limited amendment/extension.", PALE_BLUE, 82)
    c.showPage()

    p = PageWriter(c, "Quanex credit committee memorandum", 8, total, appendix=True)
    p.section("Appendix A - Historical financial summary")
    p.table(["USD millions / ratio", "FY2021", "FY2022", "FY2023", "FY2024", "FY2025"], [
        ["Revenue", "$1,072.149", "$1,221.502", "$1,130.583", "$1,277.862", "$1,837.641"],
        ["Operating income", "$81.870", "$111.281", "$110.701", "$54.826", "$(193.952)"],
        ["Unadjusted EBITDA", "$124.602", "$151.390", "$153.567", "$115.154", "$(90.508)"],
        ["Lender-base EBITDA", "$124.602", "$151.390", "$153.567", "$179.358", "$225.344"],
        ["CFO", "$78.588", "$97.965", "$147.052", "$88.812", "$164.897"],
        ["FCF", "$54.580", "$64.844", "$109.662", "$51.726", "$102.255"],
        ["CFO / lender EBITDA", "63.1%", "64.7%", "95.8%", "49.5%", "73.2%"],
        ["FCF / lender EBITDA", "43.8%", "42.8%", "71.4%", "28.8%", "45.4%"],
    ], [132, 78, 78, 78, 78, 84], row_height=28, font_size=7.1)
    p.heading("Comparability notes")
    for text in [
        "FY2021-FY2023 are pre-Tyman. FY2024 contains roughly three months of Tyman. FY2025 is the first full post-Tyman fiscal year.",
        "Reported, company pro forma, analyst comparability, and credit-adjusted layers remain separate. Current segment history is not fabricated for prior periods.",
        "FY2025 unadjusted EBITDA is negative because operating income includes the goodwill impairment; leverage and coverage using a nonpositive denominator are N/M, never favorable.",
        "Historical FCF is CFO less capital expenditures; cash interest is already included in US-GAAP CFO and is not deducted twice.",
    ]:
        p.bullet(text, size=8.3)
    p.heading("Selected FY2024/FY2025 lender-base adjustment bridge")
    p.table(["Period", "Starting EBITDA", "Accepted / deducted items", "Lender Base"], [
        ["FY2024", "$115.154m", "$0 plant closure; $(4.196)m gain; $29.076m PPA; $39.324m Tyman fees", "$179.358m"],
        ["FY2025", "$(90.508)m", "$302.284m impairment; $9.007m PPA; $4.561m noncash restructuring; other items $0", "$225.344m"],
    ], [75, 100, 270, 83], row_height=42, font_size=7.0)
    p.paragraph("Contractual EBITDA remains a partial, unofficial public-information reconstruction. Lender-normalization judgments do not alter historical cash outflows or eliminate acquisition and asset-quality risk.", size=8.4)
    c.showPage()

    p = PageWriter(c, "Quanex credit committee memorandum", 9, total, appendix=True)
    p.section("Appendix B - Scenario and covenant matrix")
    p.table(["Path", "Maximum quarterly-test leverage", "Min coverage", "All-in liquidity", "First warning", "First breach", "First payment failure", "Maturity gap"], [
        ["Base", "3.23x", "5.39x", "$263.902m", "None", "None", "None", "$324.780m"],
        ["Moderate U", "4.49x", "3.21x", "$165.078m", "10/31/26", "10/31/26", "None", "$408.375m"],
        ["Moderate M", "4.47x", "3.22x", "$168.937m", "10/31/26", "10/31/26", "None", "$381.133m"],
        ["Severe U", "7.06x", "1.78x", "$0", "04/30/26", "10/31/26", "12/31/27 interest", "$604.258m"],
        ["Severe M", "6.95x", "1.80x", "$0", "04/30/26", "10/31/26", "01/31/28 principal", "$554.718m"],
    ], [74, 62, 62, 74, 62, 62, 95, 70], row_height=42, font_size=6.4)
    p.heading("Proposed covenant and warning framework")
    p.table(["Measure", "Proposed covenant", "Analyst warning", "Key limitation"], [
        ["Gross funded leverage", "3.50x / 3.25x / 3.00x", "3.25x / 3.00x / 2.75x", "Zero cash netting; final debt/EBITDA definitions required"],
        ["Cash-interest coverage", "Minimum 3.00x", "At or below 3.50x", "Opening LTM cash interest is N/D"],
        ["Usable liquidity", "Minimum $50m", "At or below $75m", "Eligible cash and drawability require documents"],
        ["Operating cash floor", "Model control: $25m", "Separate", "Not a source or covenant cash-netting amount"],
    ], [118, 120, 118, 172], row_height=42, font_size=7.0)
    p.heading("Intervention sequence")
    for text in [
        "Warning: suspend repurchases, start monthly reporting, and require a 10-business-day action plan. A warning is not a breach.",
        "Breach: suspend restricted payments and evaluate draw conditions, cure, consent, or waiver under executed documents.",
        "No-waiver sensitivity: modeled draw shutoff starts after a tested breach; it is not a legal conclusion or automatic favorable debt reduction.",
        "Mandatory-payment failure, liquidity failure, reporting exception, covenant breach, and maturity shortfall remain distinct event classes.",
    ]:
        p.bullet(text, size=8.3)
    p.callout("Scenario boundary", "Moderate and severe cases are owner-reviewed analytical stresses, not management forecasts. Mitigations are separate dated actions and do not overwrite the unmitigated case.", PALE_TAN, 52)
    c.showPage()

    p = PageWriter(c, "Quanex credit committee memorandum", 10, total, appendix=True)
    p.section("Appendix C - Conditions, monitoring, and open diligence")
    conditions = read_csv(root / "data" / "phase10" / "processed" / "CONDITIONS_AND_MONITORING.csv")
    rows = [[r["requirement_id"], r["category"].replace("_", " "), r["requirement"], r["consequence_if_unmet"]] for r in conditions]
    p.table(["ID", "Category", "Requirement", "Consequence / control value"], rows,
            [58, 92, 185, 193], row_height=20, font_size=5.8, header_height=25)
    p.paragraph("All items remain open and not satisfied from public information. Their inclusion does not imply borrower agreement or final legal drafting. See data/phase10/processed/CONDITIONS_AND_MONITORING.csv for full evidence definitions and source IDs.", size=7.6)
    c.showPage()

    p = PageWriter(c, "Quanex credit committee memorandum", 11, total, appendix=True)
    p.section("Appendix D - Recovery sensitivities and source notes")
    p.image(charts[2], 520, 230)
    p.table(["Method", "Low", "Base", "High", "Boundary"], [
        ["Going concern", "34.006% / $289.342m", "47.795% / $406.662m", "61.583% / $523.982m", "Continued-operation EV sensitivity"],
        ["Asset realization", "16.200% / $137.840m", "33.605% / $285.927m", "49.983% / $425.285m", "Full consolidated-access ceiling"],
    ], [100, 104, 104, 104, 116], row_height=48, font_size=7.0)
    p.callout("Official conclusion: N/D",
              "The public record does not establish complete guarantor, collateral, lien, priority, cash/asset access, appraisal, or claims facts. Going-concern and asset-realization methods are alternatives and are never added.", PALE_RED, 61)
    p.heading("Definition and source notes")
    for text in [
        "The illustrative facility claim is $850.851m at the selected severe unmitigated first cash-interest failure date, December 31, 2027.",
        "The $62.619m retained finance-lease and other-funded-obligation deduction is applied once for conservative sensitivity and creates no legal-priority inference.",
        "The 100% consolidated-access case is only a mechanical ceiling. Actual lender accessibility remains N/D.",
        "Every material figure maps to a P10M record and then to an approved prior-phase path in docs/phase-10/SOURCE_LEDGER.csv.",
        "No substantive evidence first published after December 15, 2025 is used. This is not an appraisal, official compliance certificate, legal opinion, or bank decision.",
    ]:
        p.bullet(text, size=8.1)
    c.save()
    return path


def draw_wrapped(c: canvas.Canvas, text: str, x: float, y: float, width: float,
                 size: float = 8, leading: float = 10, bold: bool = False,
                 color=TEXT) -> float:
    font_name = "Helvetica-Bold" if bold else "Helvetica"
    c.setFillColor(color)
    c.setFont(font_name, size)
    words = text.split()
    line = ""
    for word in words:
        candidate = word if not line else line + " " + word
        if stringWidth(candidate, font_name, size) <= width:
            line = candidate
        else:
            c.drawString(x, y, line)
            y -= leading
            line = word
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def build_brief(root: Path, metrics: dict[tuple[str, str], dict[str, str]]) -> Path:
    path = root / "reports" / "committee_brief.pdf"
    page = landscape(LETTER)
    width, height = page
    c = canvas.Canvas(str(path), pagesize=page, pageCompression=1, invariant=1)
    c.setTitle("Quanex Credit Committee Brief")
    c.setFillColor(NAVY)
    c.rect(0, height - 55, width, 55, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(32, height - 31, "Quanex credit committee brief")
    c.setFont("Helvetica", 8)
    c.drawRightString(width - 32, height - 24, "Committee / information cutoff: December 15, 2025")
    c.drawRightString(width - 32, height - 38, "Hypothetical closing: January 31, 2026")
    c.setFillColor(PALE_BLUE)
    c.roundRect(32, height - 125, width - 64, 55, 4, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(43, height - 88, "CONDITIONAL APPROVAL - PROCEED WITH DILIGENCE AND DEFINITIVE DOCUMENTATION")
    c.setFont("Helvetica", 8)
    c.drawString(43, height - 103, "$635m term + $300m revolver | $29.898m opening draw | Hold <= $50m | owner_reviewed")
    c.setFont("Helvetica-Bold", 7.4)
    c.drawString(43, height - 116, NO_FINAL_AUTHORIZATION)

    left_x, right_x = 32, 410
    col_w = 350
    top = height - 144
    c.setFillColor(BLUE)
    c.rect(left_x, top - 19, col_w, 19, fill=1, stroke=0)
    c.rect(right_x, top - 19, col_w, 19, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left_x + 7, top - 13, "Transaction, purpose, and repayment")
    c.drawString(right_x + 7, top - 13, "Decision metrics")
    y = top - 34
    y = draw_wrapped(c, "Borrower: Quanex Building Products Corporation. Purpose: maturity extension, liquidity structure, amortization, lender protections, and monitoring - not faster same-horizon debt reduction.", left_x + 5, y, col_w - 10, 7.8, 9.4)
    y -= 4
    y = draw_wrapped(c, "Primary repayment: recurring operating cash after all required uses. Amortization/sweep are payment mechanisms. Cash and legally drawable revolver are liquidity support only. Refinancing is an unresolved maturity dependency. Recovery is the secondary backstop; official recovery N/D.", left_x + 5, y, col_w - 10, 7.8, 9.4)

    rows = [
        ("FY2025 EBITDA / historical cash-paid cov.", f"{value(metrics, 'lender_base_ebitda', 'FY2025')} / {value(metrics, 'historical_lender_ebitda_to_disclosed_cash_interest_paid', 'FY2025')}"),
        ("Opening funded debt / leverage", "$727.517m / 3.2285x"),
        ("Base minimum liquidity over forecast", "$263.902m"),
        ("Base minimum coverage over forecast", "5.3860x"),
        ("07/31/29 total debt E / R / S", "$495.368m / $507.954m / $514.754m"),
        ("01/31/31 selected bank-debt gap", "$324.780m"),
        ("Project risk / official recovery", "Elevated / N/D"),
    ]
    ry = top - 27
    for index, (label, shown) in enumerate(rows):
        if index % 2:
            c.setFillColor(GRAY)
            c.rect(right_x, ry - 22, col_w, 22, fill=1, stroke=0)
        c.setFillColor(TEXT)
        c.setFont("Helvetica", 7.6)
        c.drawString(right_x + 6, ry - 14, label)
        c.setFont("Helvetica-Bold", 7.8)
        c.drawRightString(right_x + col_w - 6, ry - 14, shown)
        ry -= 22

    base_y = 290
    blocks = [
        (32, "Decisive strengths", PALE_BLUE, [
            "FY2025 CFO/FCF recovery and full-year post-Tyman earnings capacity.",
            "Base interim debt service; substantial opening liquidity.",
            "7.5% amortization, 50% ECF sweep, covenants, and early monitoring.",
            "Explicit existing-facility fallback and capped bank hold.",
        ]),
        (224, "Decisive risks / downside", PALE_RED, [
            "Opening leverage is close to the 3.25x warning.",
            "Tyman, margin, working capital, capex, and control execution.",
            "Moderate U/M breach 10/31/26; 4.4893x/4.4670x maximum quarterly-test leverage.",
            "U/M liquidity $165.078m/$168.937m; no payment failure; mitigation does not cure; no waiver.",
            "01/31/31 gaps: moderate U $408.375m; severe U $604.258m.",
        ]),
        (416, "Principal conditions", PALE_TAN, [
            "$15m source funded and accessible; no debt substitution.",
            "Final payoff/funds flow and satisfactory closing coverage.",
            "Final economics, covenants/draws, guarantees, collateral, and LCs.",
            "Full commitments; projections; legal/KYC/tax; reporting controls.",
        ]),
        (608, "Fallback and owner gate", GRAY, [
            "If a material condition fails, do not add debt or loosen covenants.",
            "Retain or amend existing facilities through a limited amendment/extension; economics N/D.",
            "If moderate is near expected, resize/add non-debt capital/restructure/no close.",
            "All 18 Phase 10 decisions are owner_reviewed; conditions remain open.",
        ]),
    ]
    for x, title, fill, bullets in blocks:
        c.setFillColor(fill)
        c.roundRect(x, base_y - 173, 176, 173, 4, fill=1, stroke=0)
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 8.4)
        c.drawString(x + 7, base_y - 16, title)
        yy = base_y - 35
        for bullet in bullets:
            c.setFillColor(TEXT)
            c.setFont("Helvetica", 6.9)
            c.drawString(x + 7, yy, "-")
            yy = draw_wrapped(c, bullet, x + 16, yy, 153, 6.9, 8.3)
            yy -= 3

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 8.2)
    c.drawString(32, 94, "Strongest counterargument")
    draw_wrapped(c, "Refinancing incurs fees and unresolved economics. At 07/31/2029, selected debt is $19.385m above existing. Moderate stress breaches 10/31/2026; refinancing remains unresolved; and the lower selected 01/31/2031 gap partly reflects about 18 extra months. Conditional approval accepts breach only as early intervention, with reporting, corrective action, and no automatic waiver.", 32, 81, width - 64, 7.4, 9)
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 6.8)
    c.drawString(32, 31, "Public-information hypothetical project recommendation; no final commitment or funding authorization until all material conditions are satisfied; not an official grade, legal opinion, appraisal, or recovery estimate.")
    c.drawRightString(width - 32, 31, "Page 1 of 1")
    c.save()
    return path


def build(root: Path) -> dict[str, object]:
    metrics = metric_map(root)
    charts = build_charts(root, metrics)
    memo = build_memo(root, metrics, charts)
    brief = build_brief(root, metrics)
    return {"status": "PASS", "memo": str(memo.relative_to(root)), "brief": str(brief.relative_to(root)), "charts": len(charts)}


def inspect(root: Path) -> dict[str, object]:
    memo = PdfReader(root / "reports" / "credit_memo.pdf")
    brief = PdfReader(root / "reports" / "committee_brief.pdf")
    memo_text = "\n".join(page.extract_text() or "" for page in memo.pages)
    brief_text = "\n".join(page.extract_text() or "" for page in brief.pages)
    required = [
        "1. Decision and exposure", "2. Transaction and alternatives", "3. Borrower and business risk",
        "4. Historical performance and earnings quality", "5. Debt, legal structure, and liquidity",
        "6. Base repayment and refinancing", "7. Downside and covenant intervention",
        "8. Recovery and risk assessment", "9. Conditions, monitoring, and conclusion",
    ]
    return {
        "credit_memo_pages": len(memo.pages),
        "credit_memo_body_pages": 7,
        "credit_memo_appendix_pages": len(memo.pages) - 7,
        "committee_brief_pages": len(brief.pages),
        "memo_required_sections": all(text in memo_text for text in required),
        "memo_status": "conditional approval" in memo_text.lower() and "owner_reviewed" in memo_text and NO_FINAL_AUTHORIZATION in memo_text,
        "brief_status": "conditional approval" in brief_text.lower() and "owner_reviewed" in brief_text and NO_FINAL_AUTHORIZATION in brief_text,
        "brief_disclaimer": NO_FINAL_AUTHORIZATION in brief_text and "recovery estimate" in brief_text.lower(),
        "cutoff_present": "December 15, 2025" in memo_text and "December 15, 2025" in brief_text,
        "closing_present": "January 31, 2026" in memo_text and "January 31, 2026" in brief_text,
    }


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"build", "inspect"}:
        raise SystemExit("usage: render-phase10.py build|inspect ROOT")
    root = Path(sys.argv[2]).resolve()
    result = build(root) if sys.argv[1] == "build" else inspect(root)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
