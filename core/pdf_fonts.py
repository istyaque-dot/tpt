"""Font for PDFs that has the ₹ sign (reportlab's built-in Helvetica prints a black box for ₹).
DejaVu Sans is bundled in assets/fonts (free licence, see LICENSE-DejaVu.txt)."""
import os

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
_done = None


def setup() -> tuple[str, str]:
    """Register once; returns (regular, bold) font names. Falls back to Helvetica if the files are missing."""
    global _done
    if _done:
        return _done
    try:
        from reportlab.lib.fonts import addMapping
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        pdfmetrics.registerFont(TTFont("AppSans", os.path.join(_DIR, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("AppSans-Bold", os.path.join(_DIR, "DejaVuSans-Bold.ttf")))
        addMapping("AppSans", 0, 0, "AppSans")
        addMapping("AppSans", 1, 0, "AppSans-Bold")
        addMapping("AppSans", 0, 1, "AppSans")
        addMapping("AppSans", 1, 1, "AppSans-Bold")
        _done = ("AppSans", "AppSans-Bold")
    except Exception:
        _done = ("Helvetica", "Helvetica-Bold")
    return _done


def safe(text: str) -> str:
    """Text for the PDF: keeps ₹ when the font has it, else writes Rs."""
    reg, _ = setup()
    return text if reg == "AppSans" else str(text).replace("₹", "Rs.").replace("−", "-").replace("→", "->")
